#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include "WiFiProv.h"
#include "board_config.h"
// #include "app_httpd.h"  // nếu bạn có file này, include để có startCameraServer()
void startCameraServer();
static bool init_camera();

// ==== WiFiProv (BLE) config ====
static const char *POP          = "abcd1234";
static const char *SERVICE_NAME = "PROV_123";
static const char *SERVICE_KEY  = NULL;
static const bool  RESET_PROV   = false;

static uint8_t PROV_UUID[16] = {
  0xb4,0xdf,0x5a,0x1c,0x3f,0x6b,0xf4,0xbf,0xea,0x4a,0x82,0x03,0x04,0x90,0x1a,0x02
};

static void SysProvEvent(arduino_event_t *sys_event) {
  switch (sys_event->event_id) {
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      Serial.print("[WIFI] IP: ");
      Serial.println(IPAddress(sys_event->event_info.got_ip.ip_info.ip.addr));
      break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      Serial.println("[WIFI] Disconnected. Reconnecting...");
      break;
    case ARDUINO_EVENT_PROV_START:
      Serial.println("[PROV] Start BLE provisioning. Mở app 'ESP BLE Prov' và quét QR.");
      break;
    case ARDUINO_EVENT_PROV_CRED_RECV:
      Serial.printf("[PROV] SSID: %s\n", (const char*)sys_event->event_info.prov_cred_recv.ssid);
      Serial.printf("[PROV] PASS: %s\n", (const char*)sys_event->event_info.prov_cred_recv.password);
      break;
    case ARDUINO_EVENT_PROV_CRED_FAIL:
      Serial.println("[PROV] Credentials failed (sai mật khẩu hoặc không thấy AP).");
      break;
    case ARDUINO_EVENT_PROV_CRED_SUCCESS:
      Serial.println("[PROV] Credentials OK.");
      break;
    case ARDUINO_EVENT_PROV_END:
      Serial.println("[PROV] Provisioning ended.");
      break;
    default: break;
  }
}

// ==== Camera init — cấu hình “low-power safe” cho 3.3V ====
static bool init_camera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;

  config.xclk_freq_hz = 10000000;                 // NEW: 10MHz để giảm dòng tức thời
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = FRAMESIZE_QQVGA;          // NEW: giữ QQVGA luôn
  config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;
  config.jpeg_quality = 15;                       // NEW: chất lượng cao -> dòng tăng; tăng số (15) để nén nhẹ hơn, dòng giảm

  if (psramFound()) {
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.fb_count    = 2;
  } else {
    config.fb_location = CAMERA_FB_IN_DRAM;
    config.fb_count    = 1;
  }

#if defined(CAMERA_MODEL_ESP_EYE)
  pinMode(13, INPUT_PULLUP);
  pinMode(14, INPUT_PULLUP);
#endif

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAM] init failed 0x%x\n", err);
    return false;
  }

  sensor_t *s = esp_camera_sensor_get();
  if (s->id.PID == OV3660_PID) {
    s->set_vflip(s, 1);
    s->set_brightness(s, 1);
    s->set_saturation(s, -2);
  }
  // NEW: KHÔNG nâng lên QVGA nữa để hạn dòng
  // s->set_framesize(s, FRAMESIZE_QVGA);

#if defined(CAMERA_MODEL_M5STACK_WIDE) || defined(CAMERA_MODEL_M5STACK_ESP32CAM)
  s->set_vflip(s, 1);
  s->set_hmirror(s, 1);
#endif
#if defined(CAMERA_MODEL_ESP32S3_EYE)
  s->set_vflip(s, 1);
#endif

#ifdef LED_GPIO_NUM
  // Không bật LED flash khi chỉ dùng 3.3V
#endif
  return true;
}

// ==== BLE window 20s -> end ====
static void open_ble_window_20s() {
  Serial.println("[BLE] Open provisioning window (20s)");
  WiFi.onEvent(SysProvEvent);

  WiFiProv.beginProvision(
    NETWORK_PROV_SCHEME_BLE,
    // Nếu vẫn reset ở 3.3V, thử NONE thay vì FREE_BLE:
    NETWORK_PROV_SCHEME_HANDLER_FREE_BLE,   // hoặc NETWORK_PROV_SCHEME_HANDLER_NONE
    NETWORK_PROV_SECURITY_1,
    POP, SERVICE_NAME, SERVICE_KEY,
    PROV_UUID,
    RESET_PROV
  );
  WiFiProv.printQR(SERVICE_NAME, POP, "ble");

  const uint32_t BLE_WINDOW_MS = 20000;
  uint32_t t0 = millis();
  while (millis() - t0 < BLE_WINDOW_MS) {
    delay(10);
  }
  WiFiProv.endProvision();
  Serial.println("\n[BLE] Closed after 20s");
}
void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  delay(200);

  // TẮT camera sớm để tránh kéo GPIO0 khi chỉ dùng 3.3V
  pinMode(PWDN_GPIO_NUM, OUTPUT);
  digitalWrite(PWDN_GPIO_NUM, HIGH);  // power-down OV2640 trước khi chạy BLE/WiFi

  Serial.println();

  // THỬ KẾT NỐI WIFI NHANH (5s). Nếu có sẵn cred trong NVS -> bỏ qua BLE
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setTxPower(WIFI_POWER_8_5dBm);      // giảm đỉnh dòng với 3.3V
  WiFi.begin();                            // dùng cred cũ nếu có

  Serial.print("[WIFI] Quick connect");
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 5000) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    // CHƯA PROVISION -> mở BLE 20s
    open_ble_window_20s();

    // sau BLE, thử kết nối lại (đã có cred mới)
    Serial.print("[WIFI] Connecting after BLE");
    t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
      delay(250);
      Serial.print(".");
    }
    Serial.println();
  } else {
    Serial.println("[PROV] Found stored Wi-Fi. Skipping BLE.");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("[WIFI] Connected. IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("[WIFI] Not connected yet. Camera HTTPD will start; truy cập được khi có IP.");
  }

  // KHỞI TẠO CAMERA + SERVER
  if (!init_camera()) {
    Serial.println("[CAM] Init failed. Stop.");
    return;
  }

  startCameraServer();

  Serial.print("[HTTPD] Camera Ready! Use: http://");
  Serial.print(WiFi.localIP());
  Serial.println("/");
}

void loop() {
  delay(10000);
}
