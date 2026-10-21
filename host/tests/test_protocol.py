from remkey import protocol as P


def test_mac_roundtrip():
    n = P.make_nonce()
    mac = P.compute_mac("a-long-enough-secret", n)
    assert P.verify_mac("a-long-enough-secret", n, mac)
    assert not P.verify_mac("another-long-secret!", n, mac)
    assert not P.verify_mac("a-long-enough-secret", P.make_nonce(), mac)
    assert not P.verify_mac("a-long-enough-secret", n, None)


def test_sanitize_basic():
    assert P.sanitize_cw("cq de k2ua") == "CQ DE K2UA"
    assert P.sanitize_cw("tu  \n 73") == "TU 73"
    assert P.sanitize_cw("héllo~#") == "HLLO"


def test_sanitize_single_space_survives():
    # paddle word spaces arrive as a lone space and must not be dropped
    assert P.sanitize_cw(" ") == " "


def test_sanitize_prosigns_and_raw():
    assert P.sanitize_cw("tu <sk>") == "TU {...-.-}"
    assert P.sanitize_cw("<AR> <BT> <KN>") == "+ = ("
    assert P.sanitize_cw("{...-.-}") == "{...-.-}"
    assert P.sanitize_cw("<ZZ>") == ""
    assert P.sanitize_cw("{x}") == "X"         # stray braces never reach the keyer
    assert P.sanitize_cw("{..") == ".."


def test_sanitize_length_cap():
    assert len(P.sanitize_cw("E" * 2000, max_len=100)) == 100


def test_chunks_do_not_split_raw():
    text = "A" * 58 + "{...-.-}" + "B"
    chunks = P.chunk_for_keyer(text, size=60)
    assert "".join(chunks) == text
    assert all(len(c) <= 60 for c in chunks)
    assert any(c.startswith("{...-.-}") for c in chunks)


def test_encode_decode():
    msg = {"t": "cw", "text": "CQ"}
    assert P.decode(P.encode(msg)) == msg
