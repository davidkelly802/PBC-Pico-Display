"""
main.py — Pico 2 W e-ink schedule client (Waveshare 7.5" V2, portrait)

Connects to WiFi, fetches the pre-rendered raw bitmap from eink-render's
/eink.raw endpoint, writes it directly into the display buffer, refreshes
the panel, then deep-sleeps to conserve battery until the next refresh.

CONFIRMED from live hardware testing (see test_display.py):
- Driver class: EPD_7in5 (from epd7in5_V2.py)
- Pins hardcoded inside the driver: RST=12, DC=8, CS=9, BUSY=13
- display(self, Image) takes a plain buffer (bytes/bytearray), row-major,
  100 bytes/row x 480 rows (800x480 panel hardware). Pass buffer values
  directly: 0x00=black, 0xFF=white -- no manual inversion needed.
- Clear() takes no arguments.
- The server renders in portrait and rotates before sending, so the
  800x480 buffer received here is ALREADY correctly oriented for the
  panel's native landscape buffer shape. No rotation needed on this end.

IMPORTANT: machine.deepsleep() on the Pico 2 W is a full reset, not a
suspend -- execution restarts from the top of main.py on wake, and WiFi
has to reconnect from scratch every cycle. That's expected and accounted
for below; it's not a bug if you see the board "start over" each time.
"""

import network
import urequests as requests
import machine
import time

# ── Configuration ──────────────────────────────────────────────────────────────
WIFI_SSID = "PBC_OPS"
WIFI_PASSWORD = "#livingwaTer"
EINK_URL = "http://render-app.pbc.lan:5001/eink.raw"  # match your eink-render container's IP/port

REFRESH_MINUTES = 15
WIFI_CONNECT_TIMEOUT_S = 15
FETCH_TIMEOUT_S = 10

# Panel hardware dimensions -- the buffer received from /eink.raw is
# always shaped for these, regardless of render orientation server-side.
EXPECTED_WIDTH = 800
EXPECTED_HEIGHT = 480
EXPECTED_BYTE_COUNT = (EXPECTED_WIDTH // 8) * EXPECTED_HEIGHT  # 48000


# ── WiFi ────────────────────────────────────────────────────────────────────────
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print("Connecting to WiFi...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)

        start = time.time()
        while not wlan.isconnected():
            if time.time() - start > WIFI_CONNECT_TIMEOUT_S:
                raise RuntimeError("WiFi connect timed out")
            time.sleep(0.5)

    print("WiFi connected:", wlan.ifconfig())
    return wlan


# ── Fetch ───────────────────────────────────────────────────────────────────────
def fetch_schedule_bitmap():
    """
    Fetch the raw packed bitmap and return the bytes.

    urequests' response.content already excludes HTTP headers -- the
    header parsing is handled internally by the library, so we don't
    need to worry about headers leaking into the bytes here (that issue
    only came up during local debugging with a raw curl invocation that
    captured headers alongside the body into a saved file -- urequests
    itself parses the response properly).

    Raises on any network error, unexpected status, or size mismatch, so
    the caller can decide how to handle it (skip this refresh, keep
    whatever was on the panel from last time).
    """
    response = requests.get(EINK_URL, timeout=FETCH_TIMEOUT_S)
    try:
        if response.status_code != 200:
            raise RuntimeError(f"Unexpected status code: {response.status_code}")

        width = int(response.headers.get("X-Image-Width", EXPECTED_WIDTH))
        height = int(response.headers.get("X-Image-Height", EXPECTED_HEIGHT))

        if width != EXPECTED_WIDTH or height != EXPECTED_HEIGHT:
            raise RuntimeError(
                f"Server image size {width}x{height} doesn't match "
                f"expected {EXPECTED_WIDTH}x{EXPECTED_HEIGHT}"
            )

        data = response.content

        if len(data) != EXPECTED_BYTE_COUNT:
            raise RuntimeError(
                f"Unexpected byte count: got {len(data)}, "
                f"expected {EXPECTED_BYTE_COUNT}"
            )

        return data
    finally:
        response.close()  # always release the socket, even on error


# ── Display ─────────────────────────────────────────────────────────────────────
def display_bitmap(raw_bytes):
    """
    Write the raw bitmap into the e-ink display buffer and refresh.

    Uses the confirmed-working epd7in5_V2.EPD_7in5 driver API:
        epd = EPD_7in5()
        epd.init()
        epd.display(buffer)   # buffer = raw bytes, used directly --
                                # confirmed empirically: 0x00=black,
                                # 0xFF=white, no manual inversion needed
        epd.sleep()             # power down the PANEL (separate from the
                                 # Pico's own deep sleep, called later)
    """
    from picoEpaper75 import EPD_7in5

    epd = EPD_7in5()
    epd.init()
    epd.display(raw_bytes)
    epd.sleep()


# ── Main ────────────────────────────────────────────────────────────────────────
def main():
    try:
        connect_wifi()
        raw_bytes = fetch_schedule_bitmap()
        display_bitmap(raw_bytes)
        print("Display updated successfully")
    except Exception as e:
        # Don't crash-loop on a single bad fetch/connect -- just skip this
        # refresh and try again next cycle. The old image stays on the
        # e-ink panel either way, since e-ink holds its last image with
        # zero power even through a failed refresh.
        print("Refresh failed, will retry next cycle:", e)

    # Full power-down until the next scheduled refresh. This is a reset,
    # not a suspend -- execution restarts from the top of this file on wake.
    print(f"Deep sleeping for {REFRESH_MINUTES} minutes...")
    machine.deepsleep(REFRESH_MINUTES * 60 * 1000)


main()