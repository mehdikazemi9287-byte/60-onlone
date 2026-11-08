from tests.test_catalog_publication_guard import CatalogPublicationGuardTest
from app.services import catalog_structure_service as structure
from app.core.errors import ValidationError
from tests.base import AppTestCase

class CatalogVisibilityInputTest(AppTestCase):
    def make_master(self,conn):
        return CatalogPublicationGuardTest.make_master(self,conn)

    def test_invalid_http_visibility_does_not_hide_or_rebuild(self):
        with self.db.write_transaction() as conn:
            mid=self.make_master(conn)
            structure.set_visibility(conn,master_product_id=mid,visible=True,reason="test publish")
        for body in ({}, {"visible":"false"}, {"visible":0}, {"visible":None}, [True], {"visible":1}):
            response=self.client.post(f"/api/v1/admin/catalog/products/{mid}/visibility",json=body,headers=self.admin_headers())
            self.assertEqual(response.status_code,422,response.get_json())
            with self.db.read_transaction() as conn:
                self.assertEqual(conn.execute("SELECT is_visible FROM catalog_publications WHERE master_product_id=?",(mid,)).fetchone()[0],1)
                self.assertIsNone(conn.execute("SELECT family_id FROM master_products WHERE id=?",(mid,)).fetchone()[0])
        response=self.client.post(f"/api/v1/admin/catalog/products/{mid}/visibility",json={"visible":False,"reason":"test hide"},headers=self.admin_headers())
        self.assertEqual(response.status_code,200,response.get_json())
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute("SELECT is_visible FROM catalog_publications WHERE master_product_id=?",(mid,)).fetchone()[0],0)

    def test_direct_service_requires_boolean(self):
        with self.db.write_transaction() as conn:
            for visible in (0,1,None,"false",[],{}):
                with self.assertRaises(ValidationError):
                    structure.set_visibility(conn,master_product_id=999999,visible=visible,reason="test reason")
