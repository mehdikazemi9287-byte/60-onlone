"""Seller in-person settings: read own locations, validated opening hours, toggles."""
from __future__ import annotations

from tests.base import AppTestCase


class InPersonSettingsTest(AppTestCase):
    def test_read_and_update(self):
        sup = self.create_test_supplier()
        h, loc = sup["headers"], sup["location_id"]
        items = self.client.get("/api/v1/supplier/locations/in-person", headers=h).get_json()["items"]
        self.assertEqual([i["id"] for i in items], [loc])
        url = f"/api/v1/supplier/locations/{loc}/in-person"
        good = {"can_pickup": True, "accepts_walk_in": True, "accepts_appointments": False, "public_title": "شعبهٔ مرکزی",
                "public_phone": "02188776655", "opening_hours": {"sat": "09:00-13:00,16:00-20:00", "fri": "closed"}}
        r = self.client.put(url, json=good, headers=h)
        self.assertEqual(r.status_code, 200, r.get_json())
        mine = self.client.get("/api/v1/supplier/locations/in-person", headers=h).get_json()["items"][0]
        self.assertEqual((mine["accepts_walk_in"], mine["opening_hours"]["fri"]), (True, "closed"))
        for bad in ({"opening_hours": {"sat": "18:00-09:00"}}, {"opening_hours": {"xyz": "09:00-10:00"}},
                    {"opening_hours": {"sat": "9-5"}}, {"opening_hours": "always"}, {"accepts_walk_in": 1}):
            self.assertEqual(self.client.put(url, json=bad, headers=h).status_code, 422, bad)
        other = self.create_test_supplier()
        self.assertEqual(self.client.put(url, json={"can_pickup": False}, headers=other["headers"]).status_code, 404)
