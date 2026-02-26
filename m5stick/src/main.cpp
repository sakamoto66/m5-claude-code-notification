#include <M5StickC.h>
#include <NimBLEDevice.h>

#define DEVICE_NAME      "M5-Claude-Notify"
#define SCREEN_WIDTH     160
#define SCREEN_HEIGHT     80

#define NUS_SERVICE_UUID "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define NUS_RX_UUID      "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
#define NUS_TX_UUID      "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

NimBLECharacteristic* pTxCharacteristic = nullptr;

bool pairingMode     = false;  // BtnB 押し起動時のみ true（新規ペアリング許可）
bool deviceConnected = false;
bool pendingResponse = false;
bool notifyActive    = false;  // Start / Question / Done: ボタン A で消す
bool resultActive    = false;  // ALLOW / DENY: ボタン A で消す

String receivedCmd   = "";
String currentNotify = "";
String resultMsg     = "";

int8_t currentRotation = 3;

// --- 描画ヘルパー ---

// テキストを折り返して描画
static void drawWrappedText(int y, const String& text, uint16_t color, uint16_t bg) {
    M5.Lcd.setTextSize(2);
    M5.Lcd.setTextColor(color, bg);
    const int charsPerLine = 13;
    int len = text.length();
    for (int i = 0; i < len && y < SCREEN_HEIGHT - 13; i += charsPerLine) {
        M5.Lcd.setCursor(2, y);
        M5.Lcd.print(text.substring(i, min(i + charsPerLine, len)));
        y += 18;
    }
}

// 接続状態インジケーター: "C"→緑, "P"→シアン, "W"→黄
void drawStatus(const char* msg) {
    uint16_t color = (strcmp(msg, "C") == 0) ? TFT_GREEN :
                     (strcmp(msg, "P") == 0) ? TFT_CYAN  :
                                               TFT_YELLOW;
    int x = SCREEN_WIDTH - (strlen(msg) + 2) * 12 - 2;
    M5.Lcd.setTextColor(color, TFT_BLACK);
    M5.Lcd.setTextSize(2);
    M5.Lcd.setCursor(x, 1);
    M5.Lcd.printf("[%s]", msg);
}

// ボタンガイド（許可リクエスト画面下部）
void drawButtons() {
    M5.Lcd.fillRect(0, SCREEN_HEIGHT - 13, SCREEN_WIDTH, 13, TFT_PURPLE);
    M5.Lcd.setTextSize(1);
    M5.Lcd.setTextColor(TFT_GREEN, TFT_PURPLE);
    M5.Lcd.setCursor(2, SCREEN_HEIGHT - 11);
    M5.Lcd.print("[A]ALLOW");
    M5.Lcd.setTextColor(TFT_RED, TFT_PURPLE);
    M5.Lcd.setCursor(90, SCREEN_HEIGHT - 11);
    M5.Lcd.print("[B]DENY");
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

    drawWrappedText(22, args, TFT_WHITE, TFT_PURPLE);
    drawButtons();
}

// 通知表示: "Start"→紺, "Q:..."→赤, その他→緑
void drawNotify(const String& msg) {
    bool isStart    = (msg == "Start");
    bool isQuestion = msg.startsWith("Q:");
    uint16_t bg     = isStart    ? TFT_NAVY      :
                      isQuestion ? TFT_MAROON     :
                                   TFT_DARKGREEN;

    M5.Lcd.fillRect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, bg);
    M5.Lcd.setTextSize(2);
    M5.Lcd.setTextColor(TFT_WHITE, bg);
    M5.Lcd.setCursor(2, 2);
    M5.Lcd.print(isStart ? "START" : isQuestion ? "QUESTION" : "DONE");

    if (!isStart) {
        String body = isQuestion ? msg.substring(2) : msg;
        drawWrappedText(22, body, TFT_CYAN, bg);
    }
}

// 現在の画面を再描画（向き変更時など）
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
        if (pairingMode) {
            M5.Lcd.setTextSize(2);
            M5.Lcd.setTextColor(TFT_CYAN, TFT_BLACK);
            M5.Lcd.setCursor(2, 20);
            M5.Lcd.print("PAIRING");
            M5.Lcd.setTextSize(1);
            M5.Lcd.setTextColor(TFT_WHITE, TFT_BLACK);
            M5.Lcd.setCursor(2, 50);
            M5.Lcd.print(DEVICE_NAME);
        }
    }
    drawStatus(deviceConnected ? "C" : pairingMode ? "P" : "W");
}

// --- BLE コールバック ---

class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* pServer) {
        deviceConnected = true;
        resultActive    = false;
        resultMsg       = "";
        uint8_t z = 0;
        pTxCharacteristic->setValue(&z, 1);  // ボタン結果をリセット
        M5.Lcd.fillRect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, TFT_BLACK);
        drawStatus("C");
    }
    void onDisconnect(NimBLEServer* pServer) {
        deviceConnected = false;
        pendingResponse = false;
        receivedCmd     = "";
        if (!notifyActive && !resultActive) {
            M5.Lcd.fillRect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, TFT_BLACK);
        }
        drawStatus(pairingMode ? "P" : "W");
        NimBLEDevice::startAdvertising();
    }
};

class RxCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pCharacteristic) {
        String line = String(pCharacteristic->getValue().c_str());
        line.trim();
        if (line.length() == 0) return;

        // 新コマンド受信: 前回の結果をクリアして表示を更新
        notifyActive  = false;
        resultActive  = false;
        resultMsg     = "";
        uint8_t z = 0;
        pTxCharacteristic->setValue(&z, 1);  // ボタン結果をリセット

        if (line.startsWith("NOTIFY:")) {
            currentNotify = line.substring(7);
            notifyActive  = true;
            drawNotify(currentNotify);
        } else {
            receivedCmd     = line;
            pendingResponse = true;
            drawCommand(receivedCmd);
        }
    }
};

// --- BLE 初期化 ---

void setupBLE() {
    NimBLEDevice::init(DEVICE_NAME);

    if (pairingMode) {
        NimBLEDevice::deleteAllBonds();
    }

    // ボンディング設定（Just Works方式）
    NimBLEDevice::setSecurityAuth(true, true, true);
    NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);

    NimBLEServer*  pServer  = NimBLEDevice::createServer();
    pServer->setCallbacks(new ServerCallbacks());

    NimBLEService* pService = pServer->createService(NUS_SERVICE_UUID);

    // TX: M5StickC → PC (READ ポーリング方式)
    // PC 側が 0.5s ごとに read_gatt_char で値を取得する。
    // 0x00=未押下, 0x01=ALLOW, 0x02=DENY
    // READ_ENC によりボンディング済みデバイスのみ読み取り可能。
    pTxCharacteristic = pService->createCharacteristic(
        NUS_TX_UUID,
        NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::READ_ENC);
    uint8_t z = 0;
    pTxCharacteristic->setValue(&z, 1);

    // RX: PC → M5StickC（通常モードのみ）
    if (!pairingMode) {
        NimBLECharacteristic* pRx = pService->createCharacteristic(
            NUS_RX_UUID,
            NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR | NIMBLE_PROPERTY::WRITE_ENC);
        pRx->setCallbacks(new RxCallbacks());
    }

    pService->start();

    NimBLEAdvertising* pAdv = NimBLEDevice::getAdvertising();

    if (pairingMode) {
        // Microsoft Swift Pair: デバイス名を Primary に含めることで Windows 通知を表示
        // Primary adv: 製造者データ(7B) + デバイス名(18B) + flags(3B) = 28B ≤ 31B
        // Scan response: サービス UUID（128bit = 18B）
        NimBLEAdvertisementData advData;
        std::string msData;
        msData += (char)0x06;  // Microsoft Company ID (0x0006)
        msData += (char)0x00;
        msData += (char)0x03;  // Swift Pair subtype
        msData += (char)0x00;  // Reserved
        msData += (char)0x80;  // Reserved RSSI
        advData.setManufacturerData(msData);
        advData.setName(DEVICE_NAME);
        pAdv->setAdvertisementData(advData);

        NimBLEAdvertisementData scanData;
        scanData.setCompleteServices(NimBLEUUID(NUS_SERVICE_UUID));
        pAdv->setScanResponseData(scanData);
        pAdv->setScanResponse(true);
    } else {
        pAdv->addServiceUUID(NUS_SERVICE_UUID);

        NimBLEAdvertisementData scanData;
        scanData.setName(DEVICE_NAME);
        pAdv->setScanResponseData(scanData);
        pAdv->setScanResponse(true);
    }

    pAdv->start();
}

// --- setup / loop ---

void setup() {
    M5.begin();
    M5.IMU.Init();
    M5.Lcd.setRotation(currentRotation);
    M5.Lcd.fillScreen(TFT_BLACK);
    M5.Lcd.setTextSize(1);

    // BtnB 押し起動でペアリングモードに入る（他 PC への切り替え用）
    delay(100);
    M5.update();
    pairingMode = M5.BtnB.isPressed();

    Serial.begin(115200);

    setupBLE();
    redrawCurrent();
}

void loop() {
    M5.update();

    // ペアリングモード: ボンド生成を検知したら再起動して通常モードへ
    if (pairingMode && NimBLEDevice::getNumBonds() > 0) {
        esp_restart();
    }

    // 向き検知（横長維持: rotation 1 / 3）
    static unsigned long lastOrientCheck = 0;
    if (millis() - lastOrientCheck >= 500) {
        lastOrientCheck = millis();
        float accX = 0, accY = 0, accZ = 0;
        M5.IMU.getAccelData(&accX, &accY, &accZ);
        int8_t newRotation = (accX > 0.3f) ? 1 : (accX < -0.3f) ? 3 : currentRotation;
        if (newRotation != currentRotation) {
            currentRotation = newRotation;
            M5.Lcd.setRotation(currentRotation);
            redrawCurrent();
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
        bool allow = M5.BtnA.wasPressed();
        bool deny  = M5.BtnB.wasPressed();
        if (allow || deny) {
            resultMsg       = allow ? "ALLOW" : "DENY";
            uint8_t val     = allow ? 0x01 : 0x02;
            pTxCharacteristic->setValue(&val, 1);  // PC が read_gatt_char で取得
            pendingResponse = false;
            resultActive    = true;
            redrawCurrent();
        }
    }

    delay(10);
}
