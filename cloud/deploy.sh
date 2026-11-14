#!/usr/bin/env bash
# Deploy the cloud copy of the remkey telemetry dashboard (S3 + CloudFront).
# Run from the Mac, in the repo:
#
#   cloud/deploy.sh                  first run: asks for a dashboard password, builds everything
#   cloud/deploy.sh                  later runs: updates the stack and the page
#   cloud/deploy.sh --new-password   change the password people use
#   cloud/deploy.sh --new-secret     change Claude's secret path (the old link stops working)
#   cloud/deploy.sh --new-key        new upload key for the shack PC (the old one is deleted)
#
# Settings (environment): AWS_PROFILE, REMKEY_TLM_HOST (default tlm.microwavedx.com),
# REMKEY_TLM_ZONE (default microwavedx.com), REMKEY_TLM_USER (default: asked on first run).
#
# Local state lives in cloud/cloud.env (git-ignored): the secret path, the user
# name and a hash of the password. The password itself is never stored.
set -euo pipefail

HOST="${REMKEY_TLM_HOST:-tlm.microwavedx.com}"
ZONE_NAME="${REMKEY_TLM_ZONE:-microwavedx.com}"
REGION="us-east-1"
STACK="remkey-tlm"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
ENV_FILE="$HERE/cloud.env"
PAGE="$REPO/host/remkey/web/dashboard.html"
KEY_FILE="$HOME/remkey-tlm-upload-key.txt"

new_password=0; new_secret=0; new_key=0
for arg in "$@"; do
  case "$arg" in
    --new-password) new_password=1 ;;
    --new-secret) new_secret=1 ;;
    --new-key) new_key=1 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\n== %s\n' "$*"; }
sha256hex() { if command -v shasum >/dev/null; then shasum -a 256 | cut -d' ' -f1; else sha256sum | cut -d' ' -f1; fi; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

command -v aws >/dev/null || die "the AWS CLI isn't installed (brew install awscli)"
command -v openssl >/dev/null || die "openssl not found"
[ -f "$PAGE" ] || die "can't find $PAGE"

say "AWS account"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)" || die "AWS credentials don't work (aws sts get-caller-identity failed)"
echo "account $ACCOUNT, profile ${AWS_PROFILE:-default}"
BUCKET="remkey-tlm-$ACCOUNT"

ZONE_ID="$(aws route53 list-hosted-zones-by-name --dns-name "$ZONE_NAME." \
  --query "HostedZones[?Name=='$ZONE_NAME.' && Config.PrivateZone==\`false\`].Id | [0]" --output text)"
[ -n "$ZONE_ID" ] && [ "$ZONE_ID" != "None" ] || die "no public Route 53 zone for $ZONE_NAME in this account"
ZONE_ID="${ZONE_ID##*/}"
echo "zone $ZONE_NAME = $ZONE_ID"

# ---------------------------------------------------------------- local secrets
SECRET_PATH=""; AUTH_USER=""; AUTH_HASH=""
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi
if [ -z "$SECRET_PATH" ] || [ "$new_secret" = 1 ]; then
  SECRET_PATH="$(openssl rand -hex 16)"
  echo "new secret path made"
fi
if [ -z "$AUTH_HASH" ] || [ "$new_password" = 1 ]; then
  say "Dashboard password (for people; Claude uses the secret path)"
  default_user="${REMKEY_TLM_USER:-${AUTH_USER:-tower}}"
  read -r -p "User name [$default_user]: " u
  AUTH_USER="${u:-$default_user}"
  while true; do
    read -r -s -p "Password: " p1; echo
    read -r -s -p "Again: " p2; echo
    [ "$p1" = "$p2" ] || { echo "they don't match, try again"; continue; }
    [ "${#p1}" -ge 8 ] || { echo "at least 8 characters, please"; continue; }
    break
  done
  header="Basic $(printf '%s:%s' "$AUTH_USER" "$p1" | openssl base64 -A)"
  AUTH_HASH="$(printf '%s' "$header" | sha256hex)"
  unset p1 p2 header
fi
umask 077
cat > "$ENV_FILE" <<EOF
# remkey cloud dashboard: local settings (git-ignored). Keep this file private.
SECRET_PATH=$SECRET_PATH
AUTH_USER=$AUTH_USER
AUTH_HASH=$AUTH_HASH
EOF
umask 022

# ---------------------------------------------------------------- stack
say "CloudFormation stack $STACK in $REGION (the first run takes 5-15 minutes: certificate + CloudFront)"
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file "$HERE/template.yaml" --capabilities CAPABILITY_NAMED_IAM \
  --no-fail-on-empty-changeset \
  --parameter-overrides "HostName=$HOST" "HostedZoneId=$ZONE_ID" "BucketName=$BUCKET" \
    "SecretPath=$SECRET_PATH" "AuthHash=$AUTH_HASH"

out() { aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text; }
DIST_ID="$(out DistributionId)"
UPLOAD_USER="$(out UploadUser)"

# ---------------------------------------------------------------- page
say "Dashboard page"
tmp="$(mktemp)"
sed 's/<meta name="remkey-mode" content="local">/<meta name="remkey-mode" content="cloud">/' "$PAGE" > "$tmp"
grep -q 'name="remkey-mode" content="cloud"' "$tmp" || die "couldn't switch the page to cloud mode"
aws s3 cp "$tmp" "s3://$BUCKET/index.html" --region "$REGION" \
  --content-type "text/html; charset=utf-8" --cache-control "max-age=300" --only-show-errors
rm -f "$tmp"
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/index.html" \
  --query "Invalidation.Id" --output text >/dev/null
echo "uploaded and refreshed"

# ---------------------------------------------------------------- upload key for the shack PC
say "Upload key for the shack PC ($UPLOAD_USER)"
existing="$(aws iam list-access-keys --user-name "$UPLOAD_USER" --query 'AccessKeyMetadata[].AccessKeyId' --output text)"
if [ -n "$existing" ] && [ "$new_key" = 0 ]; then
  echo "already has a key ($existing); run with --new-key to replace it"
else
  read -r key_id key_secret < <(aws iam create-access-key --user-name "$UPLOAD_USER" \
    --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)
  umask 077
  cat > "$KEY_FILE" <<EOF
Upload key for the remkey station service (write-only to s3://$BUCKET/data/).
On the shack PC, add these three lines to %USERPROFILE%\.aws\credentials
(create the folder and file if they don't exist), then delete this file.

[remkey-tlm]
aws_access_key_id = $key_id
aws_secret_access_key = $key_secret
EOF
  umask 022
  unset key_secret
  echo "new key written to $KEY_FILE (delete it once it's on the shack PC)"
  for old in $existing; do
    aws iam delete-access-key --user-name "$UPLOAD_USER" --access-key-id "$old"
    echo "deleted old key $old"
  done
fi

# ---------------------------------------------------------------- done
say "Done"
cat <<EOF
People:  https://$HOST/                 (user "$AUTH_USER" + your password)
Claude:  https://$HOST/$SECRET_PATH/data/summary.html
         https://$HOST/$SECRET_PATH/      (the page, no password: keep this link private)

In the shack PC's station.toml:
  cloud_bucket = "$BUCKET"
then, in the host folder:  .\Install-remkey.bat cloud   and restart the station service.
EOF
