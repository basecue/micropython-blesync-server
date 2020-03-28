import blesync
from bluetooth_appearance import UNKNOWN
from micropython import const
import struct

# Advertising payloads are repeated packets of the following form:
#   1 byte data length (N + 1)
#   1 byte type (see constants below)
#   N bytes type-specific data

_ADV_TYPE_FLAGS = const(0x01)
_ADV_TYPE_NAME = const(0x09)
_ADV_TYPE_UUID16_COMPLETE = const(0x3)
_ADV_TYPE_UUID32_COMPLETE = const(0x5)
_ADV_TYPE_UUID128_COMPLETE = const(0x7)
_ADV_TYPE_UUID16_MORE = const(0x2)
_ADV_TYPE_UUID32_MORE = const(0x4)
_ADV_TYPE_UUID128_MORE = const(0x6)
_ADV_TYPE_APPEARANCE = const(0x19)


# Generate a payload to be passed to gap_advertise(adv_data=...).
def advertising_payload(
    limited_disc=False,
    br_edr=False,
    name=None,
    services=None,
    appearance=UNKNOWN
):
    payload = bytearray()

    def _append(adv_type, value):
        nonlocal payload
        payload += struct.pack("BB", len(value) + 1, adv_type) + value

    _append(
        _ADV_TYPE_FLAGS,
        struct.pack("B", (0x01 if limited_disc else 0x02) + (0x00 if br_edr else 0x04)),
    )

    if name:
        _append(_ADV_TYPE_NAME, name)

    if services:
        for uuid in services:
            b = bytes(uuid)
            if len(b) == 2:
                _append(_ADV_TYPE_UUID16_COMPLETE, b)
            elif len(b) == 4:
                _append(_ADV_TYPE_UUID32_COMPLETE, b)
            elif len(b) == 16:
                _append(_ADV_TYPE_UUID128_COMPLETE, b)

    # See org.bluetooth.characteristic.gap.appearance.xml
    _append(_ADV_TYPE_APPEARANCE, struct.pack("<h", appearance))

    return payload


class BLEServer:
    def __init__(self, name, *services, appearance=UNKNOWN):
        self._services = services
        self._service_by_handle = {}
        self._advertising_payload = advertising_payload(
            name=name,
            appearance=appearance
        )

    def start(self):
        blesync.active(True)
        ble_services = [
            (service.uuid, list(service.characteristics.items()))
            for service in self._services
        ]
        handles_for_services = blesync.gatts_register_services(ble_services)

        for handles, service in zip(handles_for_services, self._services):
            # TODO rework to uuid ?
            service.register_handles(*handles)
            for handle in handles:
                self._service_by_handle[handle] = service

        blesync.on_central_connect(self._on_central_connect)
        blesync.on_central_disconnect(self._on_central_disconnect)
        blesync.on_gatts_write(self._on_gatts_write)
        self._advertise()

    def _advertise(self, interval_us=500000):
        blesync.gap_advertise(interval_us, adv_data=self._advertising_payload)

    def _on_gatts_write(self, conn_handle, value_handle):
        try:
            service = self._service_by_handle[value_handle]
        except KeyError:
            pass
        else:
            received_data = blesync.gatts_read(value_handle)
            service.on_data_received(conn_handle, value_handle, received_data)

    def _on_central_connect(self, conn_handle, addr_type, addr):
        self._advertise()

    def _on_central_disconnect(self, conn_handle, addr_type, addr):
        # Start advertising again to allow a new connection.
        self._advertise()
