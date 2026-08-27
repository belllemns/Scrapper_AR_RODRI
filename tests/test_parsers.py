from aerolineas_argentinas.parsers import parse_ancillaries, select_offer


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
