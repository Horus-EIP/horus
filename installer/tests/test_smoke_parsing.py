from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import smoke  # noqa: E402


def server_frame(fin: bool, opcode: int, payload: bytes) -> bytes:
    head = bytearray()
    head.append((0x80 if fin else 0x00) | opcode)
    n = len(payload)
    if n < 126:
        head.append(n)
    elif n < (1 << 16):
        head.append(126)
        head += struct.pack("!H", n)
    else:
        head.append(127)
        head += struct.pack("!Q", n)
    return bytes(head) + payload

class TestMultipart(unittest.TestCase):
    def test_exact_body_for_one_file(self):
        built = smoke.build_multipart(
            [("files", "report.md", "text/markdown", b"# hello\n")],
            boundary="BOUND",
        )
        self.assertEqual(len(built), 2)
        ctype, body = built
        self.assertEqual(ctype, "multipart/form-data; boundary=BOUND")
        self.assertEqual(
            body,
            b"--BOUND\r\n"
            b'Content-Disposition: form-data; name="files"; filename="report.md"\r\n'
            b"Content-Type: text/markdown\r\n"
            b"\r\n"
            b"# hello\n"
            b"\r\n"
            b"--BOUND--\r\n",
        )

    def test_field_name_repeats_for_a_list_upload(self):
        _ctype, body = smoke.build_multipart(
            [
                ("files", "a.md", "text/markdown", b"A"),
                ("files", "b.md", "text/markdown", b"B"),
            ],
            boundary="B2",
        )
        self.assertEqual(body.count(b'name="files"'), 2)
        self.assertEqual(body.count(b"--B2\r\n"), 2)
        self.assertTrue(body.endswith(b"--B2--\r\n"))

    def test_binary_payload_survives_untouched(self):
        blob = bytes(range(256))
        _ctype, body = smoke.build_multipart(
            [("files", "x.bin", "application/octet-stream", blob)], boundary="B3"
        )
        self.assertIn(blob, body)

    def test_quotes_and_newlines_cannot_break_out_of_the_header(self):
        _ctype, body = smoke.build_multipart(
            [("files", 'ev"il\r\n.md', "text/plain", b"x")], boundary="B4"
        )
        header = body.split(b"\r\n")[1]
        self.assertEqual(
            header,
            b'Content-Disposition: form-data; name="files"; filename="ev%22il.md"',
        )

    def test_boundary_is_generated_when_not_supplied(self):
        ctype, body = smoke.build_multipart([("files", "a.md", "text/plain", b"a")])
        boundary = ctype.split("boundary=", 1)[1]
        self.assertTrue(boundary.startswith("----horus-smoke-"))
        self.assertIn(boundary.encode(), body)

class TestFrameEncoding(unittest.TestCase):
    def test_client_frame_is_masked(self):
        raw = smoke.encode_frame(smoke.OP_TEXT, b"hello", mask_key=b"\x01\x02\x03\x04")
        self.assertEqual(raw[0], 0x81)
        self.assertEqual(raw[1], 0x80 | 5)
        self.assertEqual(raw[2:6], b"\x01\x02\x03\x04")
        self.assertEqual(raw[6:], bytes(b ^ b"\x01\x02\x03\x04"[i % 4]
                                        for i, b in enumerate(b"hello")))
        self.assertNotIn(b"hello", raw)

    def test_masking_is_random_per_frame(self):
        a = smoke.encode_frame(smoke.OP_TEXT, b"same payload")
        b = smoke.encode_frame(smoke.OP_TEXT, b"same payload")
        self.assertNotEqual(a, b)

    def test_extended_length_16_bit(self):
        payload = b"x" * 200
        raw = smoke.encode_frame(smoke.OP_BINARY, payload, mask_key=b"\x00\x00\x00\x00")
        self.assertEqual(raw[1], 0x80 | 126)
        self.assertEqual(struct.unpack("!H", raw[2:4])[0], 200)
        self.assertEqual(raw[8:], payload)

    def test_extended_length_64_bit(self):
        payload = b"y" * 70000
        raw = smoke.encode_frame(smoke.OP_BINARY, payload, mask_key=b"\x00\x00\x00\x00")
        self.assertEqual(raw[1], 0x80 | 127)
        self.assertEqual(struct.unpack("!Q", raw[2:10])[0], 70000)

    def test_bad_mask_key_is_rejected(self):
        with self.assertRaises(ValueError):
            smoke.encode_frame(smoke.OP_TEXT, b"x", mask_key=b"\x01\x02")

class TestFrameDecoding(unittest.TestCase):
    def test_round_trip_of_a_masked_client_frame(self):
        raw = smoke.encode_frame(smoke.OP_TEXT, b"round trip")
        frame, used = smoke.decode_frame(raw)
        self.assertEqual(used, len(raw))
        self.assertTrue(frame.fin)
        self.assertEqual(frame.opcode, smoke.OP_TEXT)
        self.assertEqual(frame.payload, b"round trip")

    def test_unmasked_server_frame(self):
        raw = server_frame(True, smoke.OP_TEXT, b'{"type":"agent"}')
        frame, used = smoke.decode_frame(raw)
        self.assertEqual(used, len(raw))
        self.assertEqual(frame.payload, b'{"type":"agent"}')

    def test_partial_buffers_are_not_an_error(self):
        raw = server_frame(True, smoke.OP_TEXT, b"z" * 300)
        for cut in (0, 1, 2, 3, 4, len(raw) - 1):
            frame, used = smoke.decode_frame(raw[:cut])
            self.assertIsNone(frame, f"decoded a truncated buffer at {cut} bytes")
            self.assertEqual(used, 0)
        frame, used = smoke.decode_frame(raw)
        self.assertEqual(len(frame.payload), 300)
        self.assertEqual(used, len(raw))

    def test_two_frames_in_one_read(self):
        buf = server_frame(True, smoke.OP_TEXT, b"one") + server_frame(True, smoke.OP_TEXT, b"two")
        first, used = smoke.decode_frame(buf)
        self.assertEqual(first.payload, b"one")
        second, _ = smoke.decode_frame(buf[used:])
        self.assertEqual(second.payload, b"two")

    def test_extended_length_decodes(self):
        payload = b"p" * 70000
        frame, used = smoke.decode_frame(server_frame(True, smoke.OP_BINARY, payload))
        self.assertEqual(frame.payload, payload)
        self.assertEqual(used, 10 + 70000)

class TestMessageAssembly(unittest.TestCase):
    def test_fragmented_text_message(self):
        asm = smoke.MessageAssembler()
        self.assertIsNone(asm.push(smoke.Frame(False, smoke.OP_TEXT, b'{"content":"')))
        self.assertIsNone(asm.push(smoke.Frame(False, smoke.OP_CONT, b"4.2M")))
        result = asm.push(smoke.Frame(True, smoke.OP_CONT, b'"}'))
        self.assertEqual(result, (smoke.OP_TEXT, b'{"content":"4.2M"}'))

    def test_ping_interleaved_in_a_fragmented_message(self):
        asm = smoke.MessageAssembler()
        asm.push(smoke.Frame(False, smoke.OP_TEXT, b"part1"))
        self.assertEqual(
            asm.push(smoke.Frame(True, smoke.OP_PING, b"hb")),
            (smoke.OP_PING, b"hb"),
        )
        self.assertEqual(
            asm.push(smoke.Frame(True, smoke.OP_CONT, b"part2")),
            (smoke.OP_TEXT, b"part1part2"),
        )

    def test_unfragmented_message_passes_straight_through(self):
        asm = smoke.MessageAssembler()
        self.assertEqual(
            asm.push(smoke.Frame(True, smoke.OP_TEXT, b"whole")),
            (smoke.OP_TEXT, b"whole"),
        )

    def test_ping_alone_is_returned_immediately(self):
        asm = smoke.MessageAssembler()
        self.assertEqual(
            asm.push(smoke.Frame(True, smoke.OP_PING, b"")), (smoke.OP_PING, b"")
        )

    def test_stray_continuation_is_a_protocol_error(self):
        asm = smoke.MessageAssembler()
        with self.assertRaises(smoke.WebSocketError):
            asm.push(smoke.Frame(True, smoke.OP_CONT, b"orphan"))

    def test_overlapping_data_messages_are_a_protocol_error(self):
        asm = smoke.MessageAssembler()
        asm.push(smoke.Frame(False, smoke.OP_TEXT, b"open"))
        with self.assertRaises(smoke.WebSocketError):
            asm.push(smoke.Frame(True, smoke.OP_TEXT, b"another"))

class TestHandshake(unittest.TestCase):
    def test_accept_matches_the_rfc_example(self):
        self.assertEqual(
            smoke.expected_accept("dGhlIHNhbXBsZSBub25jZQ=="),
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=",
        )

    def test_request_has_the_required_headers(self):
        raw = smoke.build_handshake("localhost:8000", "/chat/1/?token=abc", "KEY==")
        text = raw.decode("ascii")
        self.assertTrue(text.startswith("GET /chat/1/?token=abc HTTP/1.1\r\n"))
        self.assertIn("Host: localhost:8000\r\n", text)
        self.assertIn("Upgrade: websocket\r\n", text)
        self.assertIn("Connection: Upgrade\r\n", text)
        self.assertIn("Sec-WebSocket-Key: KEY==\r\n", text)
        self.assertIn("Sec-WebSocket-Version: 13\r\n", text)
        self.assertTrue(text.endswith("\r\n\r\n"))

class TestAnswerMatching(unittest.TestCase):
    GOOD = [
        "Q4 2025 revenue for FinCorp was $4.2M.",
        "FinCorp reported revenue of 4.2 million in Q4.",
        "In Q4 2025, revenue reached 4,200,000 USD.",
    ]
    BAD = [
        "I don't have that information.",
        "Revenue was 3.1M in Q4.",
    ]

    def test_good_answers_pass(self):
        for text in self.GOOD:
            with self.subTest(text=text):
                self.assertIsNotNone(smoke.ANSWER_RE.search(text))
                ok, why = smoke.check_answer(text)
                self.assertTrue(ok, f"{text!r} was rejected: {why}")

    def test_bad_answers_fail(self):
        for text in self.BAD:
            with self.subTest(text=text):
                self.assertIsNone(smoke.ANSWER_RE.search(text))
                ok, _why = smoke.check_answer(text)
                self.assertFalse(ok, f"{text!r} was accepted")

    def test_right_number_wrong_context_is_rejected(self):
        ok, why = smoke.check_answer("The bridge is 4.2 million metres long.")
        self.assertFalse(ok)
        self.assertIn("coincidental", why)

    def test_a_bare_figure_is_accepted(self):
        for text in ("**$4.2M**", "$4.2M", "4,200,000", "4.2 million"):
            with self.subTest(text=text):
                ok, why = smoke.check_answer(text)
                self.assertTrue(ok, f"{text!r} was rejected: {why}")

    def test_context_words_are_not_required_when_the_figure_stands_alone(self):
        ok, _ = smoke.check_answer("**$4.2M**")
        self.assertTrue(ok)

    def test_one_context_word_is_enough(self):
        for text in ("Revenue was $4.2M.", "Q4: 4.2M", "FinCorp: 4.2 million"):
            with self.subTest(text=text):
                self.assertTrue(smoke.check_answer(text)[0])

    def test_lowercase_and_empty_input(self):
        self.assertTrue(smoke.check_answer("q4 revenue: 4.2m")[0])
        self.assertFalse(smoke.check_answer("")[0])

    def test_negative_control_regex(self):
        self.assertIsNotNone(smoke.NEGATIVE_RE.search("The capital of Peru is Lima."))
        self.assertIsNone(smoke.NEGATIVE_RE.search("That is not in the documents."))
        self.assertIsNone(smoke.NEGATIVE_RE.search("Climate limitations apply."))

class TestFrameClassification(unittest.TestCase):
    def test_specialist_answer_is_accepted(self):
        self.assertTrue(
            smoke._is_answer_frame(
                {
                    "type": "task_complete",
                    "content": "Q4 revenue was $4.2M.",
                    "agent_name": "Finance-Analyst",
                    "skill_used": "financial_analysis",
                }
            )
        )

    def test_manager_and_planning_frames_are_ignored(self):
        self.assertFalse(
            smoke._is_answer_frame(
                {"type": "task_complete", "content": "Plan: ...", "agent_name": "Manager"}
            )
        )
        self.assertFalse(
            smoke._is_answer_frame(
                {"type": "task_complete", "content": "Plan: ...", "skill_used": "planning"}
            )
        )

    def test_progress_and_empty_frames_are_ignored(self):
        self.assertFalse(
            smoke._is_answer_frame({"type": "task_step", "step_type": "reasoning.start"})
        )
        self.assertFalse(smoke._is_answer_frame({"type": "agent", "content": "   "}))

class TestMiscParsing(unittest.TestCase):
    def test_token_is_redacted_from_a_url(self):
        red = smoke._redact_token("ws://localhost:8000/chat/3/?token=ey.SECRET.sig")
        self.assertEqual(red, "ws://localhost:8000/chat/3/?token=<redacted>")
        self.assertNotIn("SECRET", red)

    def test_env_parsing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "# comment\n"
                "SUPER_USER_USERNAME=admin\n"
                'SUPER_USER_PASSWORD="p#ss word"\n'
                "EMPTY=\n"
                "DUP=first\n"
                "DUP=second\n"
                "not a pair\n",
                encoding="utf-8",
            )
            env = smoke.read_env(path)
        self.assertEqual(env["SUPER_USER_USERNAME"], "admin")
        self.assertEqual(env["SUPER_USER_PASSWORD"], "p#ss word")
        self.assertEqual(env["EMPTY"], "")
        self.assertEqual(env["DUP"], "second")
        self.assertNotIn("not a pair", env)

    def test_answer_text_extraction(self):
        self.assertEqual(smoke._extract_text("plain"), "plain")
        self.assertEqual(smoke._extract_text({"output": "from dict"}), "from dict")
        self.assertEqual(smoke._extract_text('{"result": "from json"}'), "from json")
        self.assertEqual(smoke._extract_text([{"content": "from list"}]), "from list")
        self.assertEqual(smoke._extract_text(None), "")
        self.assertEqual(smoke._extract_text({}), "")

if __name__ == "__main__":
    unittest.main(verbosity=2)
