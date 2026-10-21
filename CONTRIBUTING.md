# Contributing

Issues and pull requests are welcome, especially reports from real hardware.

## Running the checks locally

```
cd host
python -m pip install -e ".[test]" ruff
ruff check .
python -m pytest -q
cd ..
tests/firmware_sim/run.sh          # needs g++
```

The firmware builds with the Arduino IDE or `arduino-cli`:

```
arduino-cli compile --fqbn arduino:avr:nano \
  --build-property "build.extra_flags=-DREMKEY_ROLE=2" firmware/remkey
```

CI runs all of the above (Python on Linux, Windows and macOS; every firmware image)
on each push and pull request.

## Ground rules

- Anything that can key a transmitter must fail safe: if a link, process or cable
  goes away, PTT drops. Please keep or extend the safety tests when changing that code.
- The telemetry link must stay plain-text and identified (callsign in every packet).
- Keep the transverter link read-only unless a change is discussed first.
