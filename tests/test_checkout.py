import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "run_playwright_ancillaries",
    Path(__file__).parents[1] / "scripts" / "run_playwright_ancillaries.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_bootstrap_success_is_not_overwritten_by_request_failure():
    statuses = {}
    path = "/v1/rules/checkout/passengerData"

    module.update_bootstrap_status(statuses, path, 200)
    module.update_bootstrap_status(statuses, path, None)

    assert statuses[path] == 200


def test_localization_is_not_required_for_checkout_readiness():
    localization = "/v1/localization/languageBundles/es-AR_checkout"

    assert localization in module.CHECKOUT_BOOTSTRAP_PATHS
    assert localization not in module.REQUIRED_CHECKOUT_BOOTSTRAP_PATHS
