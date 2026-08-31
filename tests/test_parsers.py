from aerolineas_argentinas.parsers import (
    parse_ancillaries,
    select_offer,
    select_offer_group,
    selected_offer_details,
)


def payload(classes):
    return {"searchMetadata": {"currency": "ARS"}, "brandedOffers": {"0": [{"offers": [
        {"offerId": "1", "brandId": "EB", "fareBasis": "EBASE", "bookingClass": classes[0], "fare": {"baseFare": 100, "surcharges": 20, "taxes": 30, "total": 150}},
    ]}]}}


def test_selects_e_before_n():
    row = select_offer(payload(["E"]))
    assert row["booking_class"] == "E"
    assert row["price_without_taxes"] == 120


def test_falls_back_to_n():
    row = select_offer(payload(["N"]))
    assert row["booking_class"] == "N"


def test_does_not_substitute_other_class():
    assert select_offer(payload(["A"])) is None


def test_selects_only_base_with_e_or_n():
    data = {"searchMetadata": {"currency": "ARS"}, "brandedOffers": {"0": [{
        "offers": [
            {"offerId": "flex", "brandId": "EF", "bookingClass": "E", "cabinClass": "Economy", "fare": {"total": 140}},
            {"offerId": "base", "brandId": "EB", "bookingClass": "N", "cabinClass": "Economy", "fare": {"total": 100}},
        ],
    }]}}

    assert select_offer(data)["offer_id"] == "base"
    group, group_index, offer_index = select_offer_group(data)
    assert group["offers"][offer_index]["offerId"] == "base"
    assert group_index == 0


def test_rejects_e_or_n_outside_base():
    data = {"brandedOffers": {"0": [{"offers": [
        {"offerId": "flex", "brandId": "EF", "bookingClass": "E", "cabinClass": "Economy"},
        {"offerId": "base", "brandId": "EB", "bookingClass": "A", "cabinClass": "Economy"},
    ]}]}}

    assert select_offer(data) is None
    assert select_offer_group(data) is None


def test_matches_calendar_class_and_flight_instead_of_any_e_offer():
    data = {"brandedOffers": {"0": [
        {
            "legs": [{"segments": [{"flightNumber": 1522}]}],
            "offers": [{
                "offerId": "expensive-e",
                "brandId": "EB",
                "bookingClass": "E",
                "cabinClass": "Economy",
            }],
        },
        {
            "legs": [{"segments": [{"flightNumber": 1836}]}],
            "offers": [{
                "offerId": "calendar-n",
                "brandId": "EB",
                "bookingClass": "N",
                "cabinClass": "Economy",
            }],
        },
    ]}}

    group, group_index, offer_index = select_offer_group(
        data, requested_class="N", flight_number=1836
    )

    assert group["offers"][offer_index]["offerId"] == "calendar-n"
    assert group_index == 1


def test_parse_ancillaries_maps_baggage_groups():
    data = {"ancillaryGroups": [
        {"groupCode": "SP", "ancillaryPassengers": [{"ancillaryLegs": [{"ancillaries": [{"price": 77440}]}]}]},
        {"groupCode": "BG", "ancillaryPassengers": [{"ancillaryLegs": [{"ancillaries": [{"price": 52030}, {"price": 60500}]}]}]},
        {"groupCode": "EM", "ancillaryPassengers": [{"ancillaryLegs": [{"ancillaries": [{"price": 54450}]}]}]},
    ]}
    assert parse_ancillaries(data) == {
        "special_baggage_price": 77440.0,
        "checked_baggage_price": 52030.0,
        "checked_baggage_additional_price": 60500.0,
        "hand_baggage_price": 54450.0,
    }


def test_resolves_selected_offer_class_and_brand_totals():
    data = {
        "searchMetadata": {"currency": "ARS"},
        "brandedOffers": {"0": [{
            "legs": [{"stops": 0, "totalDuration": 125, "segments": [{
                "flightNumber": 1663,
                "departure": "2026-09-30T07:50:00",
                "arrival": "2026-09-30T09:55:00",
            }]}],
            "offers": [
                {"offerId": "1", "bookingClass": "A", "fareBasis": "AYEB", "brand": {"id": "EB", "name": "Base"}, "fare": {"total": 100}},
                {"offerId": "2", "bookingClass": "A", "fareBasis": "AYEP", "brand": {"id": "EP", "name": "Plus"}, "fare": {"total": 120}},
                {"offerId": "3", "bookingClass": "A", "fareBasis": "AYEF", "brand": {"id": "EF", "name": "Flex"}, "fare": {"total": 140}},
            ],
        }]},
    }
    result = selected_offer_details(data, "1")
    assert result["booking_class"] == "A"
    assert result["fare_basis"] == "AYEB"
    assert result["flight_number"] == 1663
    assert result["base_total"] == 100.0
    assert result["plus_total"] == 120.0
    assert result["flex_total"] == 140.0
