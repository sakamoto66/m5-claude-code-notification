#include <M5StickC.h>
#include <NimBLEDevice.h>

#define DEVICE_NAME    "M5-Claude-Notify"
#define SCREEN_WIDTH   160
#define SCREEN_HEIGHT   80
#define BTN_TIMEOUT    60000  // ms

#define NUS_SERVICE_UUID "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define NUS_RX_UUID      "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
#define NUS_TX_UUID      "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

NimBLECharacteristic* pTxCharacteristic = nullptr;

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

// BLE サーバーコールバック（接続・切断イベント）
class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* pServer) {
        deviceConnected  = true;
        helloPending     = true;
        helloScheduledAt = millis();
        resultActive     = false;
        resultMsg        = "";
        M5.Lcd.fillRect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, TFT_BLACK);
        drawStatus("C", TFT_GREEN);
    }
    void onDisconnect(NimBLEServer* pServer) {
        deviceConnected = false;
        helloPending    = false;
        pendingResponse = false;
        receivedCmd     = "";
        if (!notifyActive && !resultActive) {
            M5.Lcd.fillRect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, TFT_BLACK);
        }
        drawStatus("W", TFT_YELLOW);
        NimBLEDevice::startAdvertising();  // 切断後に再アドバタイズ
    }
};

// RX Characteristic コールバック（PC → M5StickC のデータ受信）
class RxCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pCharacteristic) {
        std::string value = pCharacteristic->getValue();
        String line = String(value.c_str());
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
};

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

    // BLE 初期化
    NimBLEDevice::init(DEVICE_NAME);

    // ボンディング設定（Windowsの標準ペアリングで使用可能）
    NimBLEDevice::setSecurityAuth(true, true, true);           // bonding, MITM, SC
    NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT); // Just Works方式

    NimBLEServer* pServer = NimBLEDevice::createServer();
    pServer->setCallbacks(new ServerCallbacks());

    NimBLEService* pService = pServer->createService(NUS_SERVICE_UUID);

    // TX Characteristic: M5StickC → PC (Notify)
    pTxCharacteristic = pService->createCharacteristic(NUS_TX_UUID, NIMBLE_PROPERTY::NOTIFY);

    // RX Characteristic: PC → M5StickC (Write, 暗号化必須)
    NimBLECharacteristic* pRxCharacteristic = pService->createCharacteristic(
        NUS_RX_UUID,
        NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR | NIMBLE_PROPERTY::WRITE_ENC);
    pRxCharacteristic->setCallbacks(new RxCallbacks());

    pService->start();

    NimBLEAdvertising* pAdv = NimBLEDevice::getAdvertising();
    pAdv->addServiceUUID(NUS_SERVICE_UUID);
    pAdv->setScanResponse(true);
    pAdv->start();

    drawStatus("W", TFT_YELLOW);
    Serial.println("[M5] BLE NUS started. Advertising...");
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
        pTxCharacteristic->setValue("hello\n");
        pTxCharacteristic->notify();
        helloPending = false;
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
            pTxCharacteristic->setValue("ALLOW\n");
            pTxCharacteristic->notify();
            pendingResponse = false;
            resultActive    = true;
            redrawCurrent();
        }
        if (M5.BtnB.wasPressed()) {
            resultMsg = "DENY";
            pTxCharacteristic->setValue("DENY\n");
            pTxCharacteristic->notify();
            pendingResponse = false;
            resultActive    = true;
            redrawCurrent();
        }
    }

    delay(10);
}
