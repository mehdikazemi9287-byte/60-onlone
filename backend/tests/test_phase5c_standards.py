"""Phase 5C — product logistics standard, GTIN and volumetric math (no app)."""
from __future__ import annotations

import unittest

from app.core.errors import ValidationError
from app.services import product_standards_service as pss
from app.services.shipment_orchestrator import code128_payload, make_tracking_number, tracking_check_digit


class GtinTest(unittest.TestCase):
    def test_valid_examples(self):
        for code in ("96385074", "036000291452", "4006381333931", "00012345600012", "۴۰۰۶۳۸۱۳۳۳۹۳۱"):
            self.assertTrue(pss.is_valid_gtin(code), code)
        self.assertEqual(pss.validate_gtin("400-6381-333931"), "4006381333931")

    def test_invalid_examples_persian_errors(self):
        cases = {"4006381333932": "gtin_bad_check_digit", "036000291453": "gtin_bad_check_digit",
                 "12345": "gtin_bad_length", "40063813339AB": "gtin_not_numeric"}
        for code, err in cases.items():
            with self.assertRaises(ValidationError) as cm:
                pss.validate_gtin(code)
            self.assertEqual(cm.exception.code, err)
            self.assertIn("GTIN", str(cm.exception))

    def test_check_digit(self):
        self.assertEqual(pss.gtin_check_digit("400638133393"), 1)
        self.assertEqual(pss.gtin_check_digit("9638507"), 4)


class SpecTest(unittest.TestCase):
    def test_volumetric_vs_actual(self):
        # 400×300×200 mm = 24,000 cm³ / 5000 = 4.8 kg
        self.assertEqual(pss.volumetric_weight_g(400, 300, 200), 4800)
        self.assertEqual(pss.billable_weight_g(2000, 400, 300, 200), 4800)       # bulky: volumetric
        self.assertEqual(pss.billable_weight_g(9000, 400, 300, 200), 9000)       # heavy: actual
        self.assertEqual(pss.volumetric_weight_g(400, 300, 200, divisor=6000), 4000)  # carrier divisor
        self.assertEqual(pss.volumetric_weight_g(1, 1, 1), 1)                    # rounds up

    def test_normalize_spec(self):
        s = pss.normalize_spec({"length_mm": 100, "width_mm": 50, "height_mm": 20, "gross_weight_g": 300,
                                "requires_cold_chain": True, "hazmat_class": "2.1", "hs_code": "3304.99",
                                "iran_code": "1" * 16, "gtin": "4006381333931"})
        self.assertEqual((s["is_perishable"], s["hs_code"], s["hazmat_class"]), (1, "330499", "2.1"))
        for bad in ({"length_mm": 0}, {"gross_weight_g": 1.5}, {"hazmat_class": "10"},
                    {"iran_code": "123"}, {"hs_code": "12"}, {"gtin": "4006381333932"}):
            base = {"length_mm": 1, "width_mm": 1, "height_mm": 1, "gross_weight_g": 1, **bad}
            with self.assertRaises(ValidationError):
                pss.normalize_spec(base)


class BarcodeTest(unittest.TestCase):
    def test_tracking_and_code128(self):
        t = make_tracking_number("TPX", 42)
        self.assertEqual(t, f"TPX000000042{tracking_check_digit('000000042')}")
        self.assertTrue(make_tracking_number("PST", 7, "return").startswith("PSTR"))
        # 104 + 48·1 + 42·2 + 42·3 + 17·4 + 18·5 + 19·6 + 35·7 = 879; 879 mod 103 = 55
        self.assertEqual(code128_payload("PJJ123C")["checksum"], 55)
        with self.assertRaises(ValidationError):
            code128_payload("کد")


if __name__ == "__main__":
    unittest.main()
