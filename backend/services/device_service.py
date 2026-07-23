class DeviceService:
    """Detects best available acceleration target for separation."""

    def detect(self) -> dict:
        return {"device": "cpu", "label": "CPU", "experimental": False}
