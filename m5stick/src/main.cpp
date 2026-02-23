#include <M5StickC.h>
#include <BluetoothSerial.h>

#define DEVICE_NAME    "M5-Claude-Notify"
#define SCREEN_WIDTH   160
#define SCREEN_HEIGHT   80
#define BTN_TIMEOUT    60000  // ms

BluetoothSerial SerialBT;

bool deviceConnected  = false;
bool pendingResponse  = false;
bool helloPending     = false;
bool notifyActive     = false;  // Start / Question / Done: ボタン A で消す
bool resultActive     = false;  // ALLOW / DENY: ボタン A で消す（次イベントでもリセット）
String receivedCmd    = "";
String currentNotify  = "";     // 通知内容（向き変更時の再描画用）
String resultMsg      = "";     // "ALLOW" or "DENY"（再描画用）
unsigned long cmdReceivedAt    = 0;
unsigned long helloScheduledAt = 0;
int8_t currentRotation = 3;

// 前方宣言
void drawStatus(const char* msg, uint16_t color);
void drawCommand(const String& cmd);
void drawButtons();
void drawNotify(const String& msg);
void redrawCurrent();

// Bluetooth SPP 接続状態コールバック
void btCallback(esp_spp_cb_event_t event, esp_spp_cb_param_t* param) {
    if (event == ESP_SPP_SRV_OPEN_EVT) {
        deviceConnected  = true;
        helloPending     = true;
        helloScheduledAt = millis();
        resultActive     = false;
        resultMsg        = "";
        M5.Lcd.fillRect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, TFT_BLACK);
        drawStatus("C", TFT_GREEN);
    } else if (event == ESP_SPP_CLOSE_EVT) {
        deviceConnected = false;
        helloPending    = false;
        pendingResponse = false;
        receivedCmd     = "";
        if (!notifyActive && !resultActive) {
            M5.Lcd.fillRect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, TFT_BLACK);
        }
        drawStatus("W", TFT_YELLOW);
    }
}

// 接続状態インジケーター（右上に小さく表示）C と W のみ
void drawStatus(const char* msg, uint16_t color) {
    int x = SCREEN_WIDTH - (strlen(msg) + 2) * 6 - 2;
    M5.Lcd.setTextColor(color, TFT_BLACK);
    M5.Lcd.setTextSize(1);
    M5.Lcd.setCursor(x, 1);
    M5.Lcd.print("[");
    M5.Lcd.print(msg);
    M5.Lcd.print("]");
}

// 許可リクエスト表示（紫背景）
void drawCommand(const String& cmd) {
    M5.Lcd.fillRect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, TFT_PURPLE);

    int colonIdx = cmd.indexOf(':');
    String tool  = (colonIdx > 0) ? cmd.substring(0, colonIdx) : cmd;
    String args  = (colonIdx > 0) ? cmd.substring(colonIdx + 1) : "";
    args.trim();

    M5.Lcd.setTextSize(2);
    M5.Lcd.setTextColor(TFT_YELLOW, TFT_PURPLE);
    M5.Lcd.setCursor(2, 2);
    M5.Lcd.print(tool.substring(0, 13));

    M5.Lcd.setTextSize(2);
    M5.Lcd.setTextColor(TFT_WHITE, TFT_PURPLE);
    const int charsPerLine = 13;
    int len = args.length();
    int y = 22;
    for (int i = 0; i < len && y < SCREEN_HEIGHT - 13; i += charsPerLine) {
        M5.Lcd.setCursor(2, y);
        M5.Lcd.print(args.substring(i, min(i + charsPerLine, len)));
        y += 18;
    }

    drawButtons();
}

// 通知表示
// "Start"       → 紺背景・START ラベル・[A]OK（notifyActive）
// "Q:..."       → 赤背景・QUESTION ラベル・[A]OK（notifyActive）
// その他(Done)  → 緑背景・DONE ラベル・[A]OK（notifyActive）
void drawNotify(const String& msg) {
    bool isStart    = (msg == "Start");
    bool isQuestion = msg.startsWith("Q:");
    uint16_t bg     = isStart    ? TFT_NAVY   :
                      isQuestion ? TFT_MAROON :
                                   TFT_DARKGREEN;

    M5.Lcd.fillRect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, bg);
    M5.Lcd.setTextSize(2);
    M5.Lcd.setTextColor(TFT_WHITE, bg);
    M5.Lcd.setCursor(2, 2);

    if (isStart) {
        M5.Lcd.print("START");
    } else if (isQuestion) {
        M5.Lcd.print("QUESTION");
    } else {
        M5.Lcd.print("DONE");
    }

    // 本文（Start は本文なし、Question は Q: を除いた部分）
    if (!isStart) {
        String body = isQuestion ? msg.substring(2) : msg;
        M5.Lcd.setTextSize(2);
        M5.Lcd.setTextColor(TFT_CYAN, bg);
        const int charsPerLine = 13;
        int len = body.length();
        int y = 22;
        for (int i = 0; i < len && y < SCREEN_HEIGHT - 13; i += charsPerLine) {
            M5.Lcd.setCursor(2, y);
            M5.Lcd.print(body.substring(i, min(i + charsPerLine, len)));
            y += 18;
        }
    }
}

// 許可リクエストのボタンガイド
void drawButtons() {
    M5.Lcd.fillRect(0, SCREEN_HEIGHT - 13, SCREEN_WIDTH, 13, TFT_PURPLE);
    M5.Lcd.setTextColor(TFT_GREEN, TFT_PURPLE);
    M5.Lcd.setTextSize(1);
    M5.Lcd.setCursor(2, SCREEN_HEIGHT - 11);
    M5.Lcd.print("[A]ALLOW");
    M5.Lcd.setTextColor(TFT_RED, TFT_PURPLE);
    M5.Lcd.setCursor(90, SCREEN_HEIGHT - 11);
    M5.Lcd.print("[B]DENY");
}

// 向き変更時に現在の画面を再描画
void redrawCurrent() {
    if (pendingResponse) {
        drawCommand(receivedCmd);
    } else if (resultActive) {
        drawCommand(receivedCmd);
        uint16_t resBg = (resultMsg == "ALLOW") ? TFT_DARKGREEN : TFT_MAROON;
        M5.Lcd.fillRect(0, SCREEN_HEIGHT - 13, SCREEN_WIDTH, 13, resBg);
        M5.Lcd.setTextColor(TFT_WHITE, resBg);
        M5.Lcd.setTextSize(1);
        M5.Lcd.setCursor(2, SCREEN_HEIGHT - 11);
        M5.Lcd.print(">>> " + resultMsg + " <<<");
    } else if (notifyActive) {
        drawNotify(currentNotify);
    } else {
        M5.Lcd.fillRect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, TFT_BLACK);
    }
    drawStatus(deviceConnected ? "C" : "W",
                deviceConnected ? TFT_GREEN : TFT_YELLOW);
}

void setup() {
    M5.begin();
    M5.IMU.Init();
    M5.Lcd.setRotation(currentRotation);
    M5.Lcd.fillScreen(TFT_BLACK);
    M5.Lcd.setTextSize(1);

    Serial.begin(115200);
    SerialBT.register_callback(btCallback);
    SerialBT.begin(DEVICE_NAME);

    drawStatus("W", TFT_YELLOW);
    Serial.println("[M5] Bluetooth SPP started.");
}

void loop() {
    M5.update();

    // 向き検知（横長維持: rotation 1 / 3 の 2 パターン）
    // accX > 0 → rotation 1、accX < 0 → rotation 3（逆の場合は符号を反転）
    static unsigned long lastOrientCheck = 0;
    if (millis() - lastOrientCheck >= 500) {
        lastOrientCheck = millis();
        float accX = 0, accY = 0, accZ = 0;
        M5.IMU.getAccelData(&accX, &accY, &accZ);
        int8_t newRotation;
        if (accX > 0.3f) {
            newRotation = 1;
        } else if (accX < -0.3f) {
            newRotation = 3;
        } else {
            newRotation = currentRotation;
        }
        if (newRotation != currentRotation) {
            currentRotation = newRotation;
            M5.Lcd.setRotation(currentRotation);
            redrawCurrent();
        }
    }

    // 接続から 500ms 後に hello を送信
    if (helloPending && (millis() - helloScheduledAt >= 500)) {
        SerialBT.println("hello");
        helloPending = false;
    }

    // コマンド受信
    if (SerialBT.available()) {
        String line = SerialBT.readStringUntil('\n');
        line.trim();
        if (line.length() > 0) {
            notifyActive = false;
            resultActive = false;
            resultMsg    = "";

            if (line.startsWith("NOTIFY:")) {
                String notifyMsg = line.substring(7);
                currentNotify = notifyMsg;
                notifyActive  = true;
                drawNotify(notifyMsg);
            } else {
                // 許可リクエスト
                pendingResponse = true;
                receivedCmd     = line;
                cmdReceivedAt   = millis();
                drawCommand(receivedCmd);
            }
        }
    }

    // 通知 / 許可結果: ボタン A で黒画面に戻る
    if ((notifyActive || resultActive) && M5.BtnA.wasPressed()) {
        notifyActive = false;
        resultActive = false;
        resultMsg    = "";
        redrawCurrent();
    }

    // 許可リクエスト: ボタン操作
    if (pendingResponse) {
        if (M5.BtnA.wasPressed()) {
            resultMsg = "ALLOW";
            SerialBT.println("ALLOW");
            pendingResponse = false;
            resultActive    = true;
            redrawCurrent();
        }
        if (M5.BtnB.wasPressed()) {
            resultMsg = "DENY";
            SerialBT.println("DENY");
            pendingResponse = false;
            resultActive    = true;
            redrawCurrent();
        }
    }

    delay(10);
}
