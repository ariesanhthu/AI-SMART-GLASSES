#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include "esp_camera.h"
#include "esp_wifi.h"

// ---------- YOUR SETTINGS ----------
#define WIFI_SSID       "iPhone"
#define WIFI_PASS       "12345678"
#define SUPABASE_HOST   "xrnbwcegjthahwyoppxp.supabase.co"
#define BUCKET_NAME     "cam"
#define SUPABASE_ANON_KEY "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhybmJ3Y2VnanRoYWh3eW9wcHhwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTg0NzA1NDIsImV4cCI6MjA3NDA0NjU0Mn0.3FuYpd5nsIwEryj8PyKsNqtSvoTyVN4C9_H7eGqb63k"
#define DEVICE_ID       "cam01"
#define CAPTURE_INTERVAL_MS 10000
// ----------------------------------

// ---- AI THINKER pin map ----
#define PWDN_GPIO_NUM  32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  0
#define SIOD_GPIO_NUM  26
#define SIOC_GPIO_NUM  27
#define Y9_GPIO_NUM    35
#define Y8_GPIO_NUM    34
#define Y7_GPIO_NUM    39
#define Y6_GPIO_NUM    36
#define Y5_GPIO_NUM    21
#define Y4_GPIO_NUM    19
#define Y3_GPIO_NUM    18
#define Y2_GPIO_NUM    5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM  23
#define PCLK_GPIO_NUM  22

// tái sử dụng client cho mọi request
WiFiClientSecure client;

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;   config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;   config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;   config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;   config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;  
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM; 
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM; 
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM; 
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;   // giữ nguyên config của bạn
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_VGA;
  config.jpeg_quality = 15;
  config.fb_count = 1;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed, err=0x%x\n", err);
    return false;
  }
  return true;
}

bool uploadToSupabase(const uint8_t* data, size_t len, const String& objectPath) {
  client.setInsecure(); // bỏ verify cert để tránh lỗi SSL

  String url = "https://" + String(SUPABASE_HOST) +
               "/storage/v1/object/" + BUCKET_NAME + "/" + objectPath;

  HTTPClient http;
  http.setReuse(true); // giữ kết nối TCP

  if (!http.begin(client, url)) {
    Serial.println("[HTTP] begin() failed");
    return false;
  }

  http.addHeader("Authorization", String("Bearer ") + SUPABASE_ANON_KEY);
  http.addHeader("apikey", SUPABASE_ANON_KEY);
  http.addHeader("Content-Type", "image/jpeg");
  http.addHeader("x-upsert", "true");

  int code = http.POST((uint8_t*)data, len);
  String resp = http.getString();
  http.end();

  Serial.printf("[HTTP] code=%d\n", code);
  if (resp.length()) Serial.printf("[HTTP] resp=%s\n", resp.c_str());

  return (code == 200 || code == 201);
}

void setup() {
  Serial.begin(115200);
  delay(500);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);   // tránh reconnect bất ngờ
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("Connecting to %s", WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500); Serial.print(".");
  }
  Serial.println();
  Serial.print("IP: "); Serial.println(WiFi.localIP());

  if (!initCamera()) {
    while (true) delay(1000);
  }
}

void loop() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Camera capture failed"); 
    delay(3000);
    return;
  }

  // luôn upload vào cam01/image.jpg
  String objectPath = String(DEVICE_ID) + "/image.jpg";

  bool ok = uploadToSupabase(fb->buf, fb->len, objectPath);
  esp_camera_fb_return(fb);

  if (ok) {
    Serial.println("Uploaded OK");
  } else {
    Serial.println("Upload failed");
  }

  delay(CAPTURE_INTERVAL_MS);
}