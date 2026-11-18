from app.services import pack_builder_service as pb


def test_bulk_occasions_map_to_real_catalog_roots():
    for key, roots in {"religious": ("supermarket",), "charity": ("supermarket",),
                       "cultural": ("books-stationery",), "stationery": ("books-stationery",)}.items():
        assert pb.OCCASION_CATEGORIES[key] == roots


def test_existing_occasions_unchanged():
    assert pb.OCCASION_CATEGORIES["livelihood"] == pb.DEFAULT_CATEGORIES
    assert pb.OCCASION_CATEGORIES["yalda"] == ("nuts-local", "gift-seasonal")
