#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>

// ============================================================
// 1. ตั้งค่า Wi-Fi Hotspot และ IP ของ Server คอมพิวเตอร์
// ============================================================
const char* ssid = "YOUR_HOTSPOT_NAME";         // ใส่ชื่อ Wi-Fi Hotspot มือถือของคุณ
const char* password = "YOUR_HOTSPOT_PASSWORD"; // ใส่รหัสผ่าน Hotspot มือถือของคุณ

// IP คอมพิวเตอร์ในเครือข่าย Hotspot (ดู IP โดยพิมพ์ ipconfig ใน CMD)
// ตัวอย่าง: "http://192.168.43.100:5000/upload"
const char* serverUrl = "http://172.30.91.187:5000/upload";

// ขากดปุ่ม IO0 (GPIO 0 บนบอร์ด ESP32-CAM)
const int BUTTON_PIN = 0;

// ============================================================
// 2. การตั้งค่า Pin สำหรับ ESP32-CAM AI Thinker
// ============================================================
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27

#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

void setup() {
  Serial.begin(115200);
  Serial.println();
  Serial.println("Initializing ESP32-CAM Button Capture System...");

  // ตั้งค่าปุ่มกด IO0
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  // ตั้งค่าโครงสร้างกล้อง ESP32-CAM
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
  config.pin_siod = SIOD_GPIO_NUM;
  config.pin_sioc = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  // ปรับคุณภาพภาพ (VGA 640x480)
  if (psramFound()) {
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = 12; // 0-63 (ค่าน้อยยิ่งชัด)
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_CIF;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }

  // เริ่มทำงานโมดูลกล้อง
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x\n", err);
    return;
  }
  Serial.println("Camera initialized successfully!");

  // เชื่อมต่อ Wi-Fi Hotspot
  WiFi.begin(ssid, password);
  Serial.print("Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.print("Wi-Fi Connected! Local IP: ");
  Serial.println(WiFi.localIP());
  Serial.println("==================================================");
  Serial.println("READY! Press IO0 button OR type 'c' in Serial Monitor to capture!");
  Serial.println("==================================================");
}

void takeAndUploadPhoto() {
  Serial.println("\n[TRIGGER] Capturing photo from ESP32-CAM...");

  // 1. ถ่ายภาพ JPEG
  camera_fb_t * fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[ERROR] Camera capture failed!");
    return;
  }
  Serial.printf("[INFO] Photo captured! Size: %u bytes\n", fb->len);

  // 2. ส่ง HTTP POST แบบ raw binary bytes ไปยัง Python Server
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "image/jpeg");

    Serial.printf("[HTTP] Sending raw bytes to %s ...\n", serverUrl);
    int httpResponseCode = http.POST(fb->buf, fb->len);

    if (httpResponseCode > 0) {
      String response = http.getString();
      Serial.printf("[HTTP SUCCESS] Response Code: %d\n", httpResponseCode);
      Serial.println("[SERVER RESPONSE]:");
      Serial.println(response);
    } else {
      Serial.printf("[HTTP ERROR] Failed to send POST. Code: %d (%s)\n",
                    httpResponseCode, http.errorToString(httpResponseCode).c_str());
    }
    http.end();
  } else {
    Serial.println("[ERROR] Wi-Fi Disconnected!");
  }

  // 3. คืนคืนหน่วยความจำเฟรมภาพ (ป้องกัน Memory Leak)
  esp_camera_fb_return(fb);
}

void loop() {
  // 1. ตรวจจับการกดปุ่ม IO0 บนบอร์ด ESP32-CAM (กดลง = LOW)
  if (digitalRead(BUTTON_PIN) == LOW) {
    delay(50); // Debounce ป้องกันปุ่มเด้ง
    if (digitalRead(BUTTON_PIN) == LOW) {
      takeAndUploadPhoto();
      while (digitalRead(BUTTON_PIN) == LOW) {
        delay(10); // รอจนกว่าผู้ใช้จะปล่อยปุ่ม IO0
      }
    }
  }

  // 2. สำรอง: สามารถพิมพ์ตัวอักษร 'c' ใน Serial Monitor เพื่อสั่งถ่ายภาพได้เช่นกัน
  if (Serial.available()) {
    char ch = Serial.read();
    if (ch == 'c' || ch == 'C') {
      takeAndUploadPhoto();
    }
  }

  delay(50);
}
