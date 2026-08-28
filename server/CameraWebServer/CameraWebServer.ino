#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>

#include "board_config.h"

// ==================================================
// Wi-Fi
// ==================================================
const char *ssid = "Chokun02";
const char *password = "chokun02";

// IP ของ Flask Server บนคอมพิวเตอร์ (พอร์ต 5001)
const char *flaskServerUrl = "http://172.29.241.183:5001/upload";

// ==================================================
// Camera Web Server เดิม
// ==================================================
void startCameraServer();
void setupLedFlash();

// ==================================================
// Command Server
// ใช้ Port 8080 แยกจากหน้าเว็บกล้อง Port 80
// ==================================================
WebServer commandServer(8080);

// ==================================================
// รับคำสั่ง /capture จาก COE.PSU
// ==================================================
void handleCapture() {

  Serial.println();
  Serial.println("================================");
  Serial.println("CAPTURE COMMAND RECEIVED FROM COE.PSU!");
  Serial.println("================================");

  camera_fb_t *fb = esp_camera_fb_get();

  if (!fb) {
    Serial.println("[ERROR] Camera capture failed!");

    commandServer.send(
      500,
      "application/json",
      "{\"success\":false,\"message\":\"Camera capture failed\"}"
    );

    return;
  }

  Serial.printf("[INFO] Photo captured: %u bytes\n", fb->len);

  // ส่งภาพ JPEG แบบ HTTP POST (raw binary bytes) ไปยัง Flask Server บนคอมพิวเตอร์
  bool uploadSuccess = false;
  String serverResponseBody = "";

  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(flaskServerUrl);
    http.addHeader("Content-Type", "image/jpeg");

    Serial.printf("[HTTP] Posting raw JPEG (%u bytes) to %s...\n", fb->len, flaskServerUrl);
    int httpCode = http.POST(fb->buf, fb->len);

    if (httpCode > 0) {
      serverResponseBody = http.getString();
      Serial.printf("[HTTP SUCCESS] Response Code: %d\n", httpCode);
      Serial.println("[FLASK RESPONSE]:");
      Serial.println(serverResponseBody);
      uploadSuccess = (httpCode == 200);
    } else {
      Serial.printf("[HTTP ERROR] POST failed, error: %s\n", http.errorToString(httpCode).c_str());
    }
    http.end();
  } else {
    Serial.println("[ERROR] WiFi is not connected!");
  }

  // ตอบกลับ COE.PSU
  if (uploadSuccess) {
    commandServer.send(
      200,
      "application/json",
      "{\"success\":true,\"message\":\"Captured and uploaded to Flask Server successfully\"}"
    );
    Serial.println("[SUCCESS] Photo sent to Flask Server successfully!");
  } else {
    commandServer.send(
      500,
      "application/json",
      "{\"success\":false,\"message\":\"Captured but failed to upload to Flask Server\"}"
    );
    Serial.println("[WARNING] Photo captured but upload to Flask Server failed!");
  }

  // คืน Frame Buffer ป้องกัน Memory Leak
  esp_camera_fb_return(fb);
}

// ==================================================
// ทดสอบ Server
// ==================================================
void handleStatus() {

  String message = "ESP32-CAM READY\n";
  message += "IP: ";
  message += WiFi.localIP().toString();
  message += "\n";

  commandServer.send(
    200,
    "text/plain",
    message
  );
}

// ==================================================
// SETUP
// ==================================================
void setup() {

  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();

  Serial.println("================================");
  Serial.println("       ESP32-CAM START");
  Serial.println("================================");

  // ==================================================
  // Camera configuration
  // ==================================================

  camera_config_t config;

  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;

  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;

  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;

  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;

  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;

  config.xclk_freq_hz = 20000000;

  config.frame_size = FRAMESIZE_UXGA;
  config.pixel_format = PIXFORMAT_JPEG;

  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location = CAMERA_FB_IN_PSRAM;

  config.jpeg_quality = 12;
  config.fb_count = 1;

  // ==================================================
  // PSRAM
  // ==================================================

  if (config.pixel_format == PIXFORMAT_JPEG) {

    if (psramFound()) {

      config.jpeg_quality = 10;
      config.fb_count = 2;
      config.grab_mode = CAMERA_GRAB_LATEST;

    } else {

      config.frame_size = FRAMESIZE_SVGA;
      config.fb_location = CAMERA_FB_IN_DRAM;
    }

  } else {

    config.frame_size = FRAMESIZE_240X240;

#if CONFIG_IDF_TARGET_ESP32S3
    config.fb_count = 2;
#endif

  }

  // ==================================================
  // Camera init
  // ==================================================

  esp_err_t err = esp_camera_init(&config);

  if (err != ESP_OK) {

    Serial.printf(
      "Camera init failed with error 0x%x\n",
      err
    );

    return;
  }

  Serial.println("Camera initialized successfully!");

  // ==================================================
  // Sensor settings
  // ==================================================

  sensor_t *s = esp_camera_sensor_get();

  if (s->id.PID == OV3660_PID) {

    s->set_vflip(s, 1);
    s->set_brightness(s, 1);
    s->set_saturation(s, -2);
  }

  if (config.pixel_format == PIXFORMAT_JPEG) {

    s->set_framesize(
      s,
      FRAMESIZE_QVGA
    );
  }

  // ==================================================
  // LED Flash
  // ==================================================

#if defined(LED_GPIO_NUM)
  setupLedFlash();
#endif

  // ==================================================
  // Wi-Fi
  // ==================================================

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  WiFi.setSleep(false);

  Serial.print("WiFi connecting");

  while (WiFi.status() != WL_CONNECTED) {

    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi connected!");

  Serial.print("ESP32-CAM IP: ");
  Serial.println(WiFi.localIP());

  // ==================================================
  // Camera Web Server เดิม
  // Port 80
  // ==================================================

  startCameraServer();

  Serial.println();
  Serial.print("Camera Web: http://");
  Serial.println(WiFi.localIP());

  // ==================================================
  // Command Server
  // Port 8080
  // ==================================================

  commandServer.on(
    "/capture",
    HTTP_GET,
    handleCapture
  );

  commandServer.on(
    "/status",
    HTTP_GET,
    handleStatus
  );

  commandServer.begin();

  Serial.println();
  Serial.println("Command Server started!");
  Serial.print("Capture URL: http://");
  Serial.print(WiFi.localIP());
  Serial.println(":8080/capture");

  Serial.println();
  Serial.println("================================");
  Serial.println("ESP32-CAM READY!");
  Serial.println("================================");
}

// ==================================================
// LOOP
// ==================================================

void loop() {

  commandServer.handleClient();

  delay(2);
}
