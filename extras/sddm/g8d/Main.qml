import QtQuick 2.15
import QtQuick.Controls 2.15 as C
import QtQuick.Layouts 1.15
import QtQuick.VirtualKeyboard 2.15
import SddmComponents 2.0 as SDDM

Rectangle {
    id: root
    width: 1920; height: 1080
    color: "#111519"
    property color accent: config.accent || "#6faede"
    property color ink: "#dbe1e5"
    property color muted: "#80909c"
    property bool busy: false
    property bool showKeyboard: false
    property string message: ""
    property string timeText: Qt.formatTime(new Date(), "HH:mm")
    property string user: userModel.lastUser || ""
    property string layoutName: keyboard.enabled && keyboard.layouts.length && keyboard.currentLayout >= 0
                                ? keyboard.layouts[keyboard.currentLayout].shortName.toUpperCase() : "US"
    function login() {
        if (busy || !root.user.trim() || !password.text) return
        message = ""; busy = true
        sddm.login(root.user.trim(), password.text, session.currentIndex)
    }
    Timer { interval: 1000; running: true; repeat: true; onTriggered: root.timeText = Qt.formatTime(new Date(), "HH:mm") }

    Item {
        id: centerpiece
        width: parent.width; height: parent.height
        anchors.centerIn: parent
        anchors.verticalCenterOffset: root.showKeyboard ? -Math.min(inputPanel.height * .4, 160) : 0
        Behavior on anchors.verticalCenterOffset { NumberAnimation { duration: 180 } }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height / 2 - 160
            text: root.timeText; color: root.ink
            font.family: "DejaVu Sans"; font.pointSize: 64; font.weight: Font.Normal
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height / 2 - 30
            text: "g8d / graphite"; color: root.accent
            font.family: "DejaVu Sans"; font.pointSize: 13
        }
        C.TextField {
            id: password; objectName: "password"
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height / 2 + 46
            width: 280; height: 48
            leftPadding: 18; rightPadding: 46
            color: root.ink; font.family: "DejaVu Sans"; font.pixelSize: 16
            placeholderText: "Пароль"; placeholderTextColor: root.muted
            horizontalAlignment: TextInput.AlignHCenter
            echoMode: reveal.down ? TextInput.Normal : TextInput.Password
            passwordCharacter: "●"; passwordMaskDelay: 0
            inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
            selectByMouse: true; focus: true; enabled: !root.busy
            background: Rectangle {
                color: "#161b20"; radius: 6
                border.width: 1; border.color: keyboard.capsLock ? "#e5b566" : root.accent
            }
            onAccepted: root.login()
            Keys.onEscapePressed: { password.text = ""; root.message = "" }
            C.ToolButton {
                id: reveal
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                width: 40; height: 40; text: "◉"
                contentItem: Text { text: reveal.text; color: reveal.down ? root.accent : root.muted; font.pixelSize: 17; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { color: "transparent" }
                onReleased: password.forceActiveFocus()
                C.ToolTip.visible: hovered
                C.ToolTip.text: "Удерживай, чтобы показать пароль"
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height / 2 + 107
            text: root.busy ? "Выполняется вход…" : root.message
            visible: text.length > 0
            color: root.busy ? root.muted : "#ef9e9e"
            font.pixelSize: 12
        }
        C.ToolButton {
            id: layout
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height / 2 + 120
            text: "Раскладка: " + root.layoutName
            visible: !root.busy && !root.message
            contentItem: Text { text: layout.text; color: root.ink; font.family: "DejaVu Sans"; font.pointSize: 13; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
            background: Rectangle { color: "transparent" }
            onClicked: { if (keyboard.layouts.length) keyboard.currentLayout = (keyboard.currentLayout + 1) % keyboard.layouts.length; password.forceActiveFocus() }
            C.ToolTip.visible: hovered
            C.ToolTip.text: "Win + Пробел или нажатие — сменить язык"
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height / 2 + 160
            text: keyboard.capsLock ? "Caps Lock включён" : "Caps Lock выключен"
            color: keyboard.capsLock ? "#e5b566" : root.muted
            font.family: "DejaVu Sans"; font.pointSize: 12
        }
    }

    C.ToolButton {
        id: userButton
        anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 28
        text: root.user + "  ⌄"
        contentItem: Text { text: userButton.text; color: userButton.hovered ? root.ink : root.muted; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { color: "transparent" }
        onClicked: { userPopup.open(); username.forceActiveFocus(); username.selectAll() }
    }
    C.Popup {
        id: userPopup
        x: 28; y: root.height - height - 82
        width: 280; padding: 16
        background: Rectangle { color: "#161b20"; border.color: "#303e46"; radius: 8 }
        contentItem: ColumnLayout {
            spacing: 12
            Text { text: "Пользователь"; color: root.muted; font.pixelSize: 12 }
            C.TextField {
                id: username; Layout.fillWidth: true
                text: root.user; color: root.ink; selectByMouse: true
                background: Rectangle { color: "#111519"; border.color: root.accent; radius: 4 }
                onAccepted: { root.user = text.trim(); password.text = ""; userPopup.close(); password.forceActiveFocus() }
            }
            C.Button {
                id: changeUser; text: "Выбрать"; Layout.fillWidth: true
                contentItem: Text { text: changeUser.text; color: root.ink; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { color: "#26333e"; radius: 4; implicitHeight: 36 }
                onClicked: { root.user = username.text.trim(); password.text = ""; userPopup.close(); password.forceActiveFocus() }
            }
        }
    }
    C.ToolButton {
        id: keyboardButton
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: root.showKeyboard ? inputPanel.top : parent.bottom
        anchors.bottomMargin: root.showKeyboard ? 8 : 28
        text: root.showKeyboard ? "Скрыть клавиатуру" : "Экранная клавиатура"
        contentItem: Text { text: keyboardButton.text; color: keyboardButton.hovered ? root.ink : root.muted; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { color: "transparent" }
        onClicked: { root.showKeyboard = !root.showKeyboard; password.forceActiveFocus(); Qt.inputMethod.show() }
    }
    C.ComboBox {
        id: session; objectName: "session"
        anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 28
        width: 230; height: 36
        model: sessionModel; textRole: "name"
        currentIndex: sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0
        contentItem: Text { text: session.displayText; color: root.muted; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; rightPadding: 26; leftPadding: 10 }
        indicator: Text { x: parent.width - 20; anchors.verticalCenter: parent.verticalCenter; text: "⌄"; color: root.muted }
        background: Rectangle { color: "transparent"; border.color: session.hovered ? "#303e46" : "transparent"; radius: 5 }
        delegate: C.ItemDelegate {
            id: sessionEntry
            width: session.width
            required property string name
            required property int index
            contentItem: Text { text: sessionEntry.name; color: sessionEntry.highlighted ? root.accent : root.ink; font.pixelSize: 13; elide: Text.ElideRight }
            background: Rectangle { color: sessionEntry.highlighted ? "#26333e" : "#161b20" }
            highlighted: session.highlightedIndex === index
        }
        popup: C.Popup {
            objectName: "session-popup"
            y: -height - 6; width: session.width; padding: 5
            implicitHeight: Math.min(contentItem.implicitHeight + 10, 260)
            background: Rectangle { color: "#161b20"; radius: 6; border.color: "#303e46" }
            contentItem: ListView { clip: true; implicitHeight: contentHeight; model: session.popup.visible ? session.delegateModel : null; currentIndex: session.highlightedIndex; C.ScrollIndicator.vertical: C.ScrollIndicator {} }
        }
        onActivated: password.forceActiveFocus()
    }
    InputPanel {
        id: inputPanel
        anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom
        width: Math.min(parent.width, 1000); visible: root.showKeyboard; z: 20
    }
    Connections {
        target: sddm
        function onLoginFailed() { root.busy = false; root.message = "Неверный пароль"; password.text = ""; password.forceActiveFocus() }
        function onInformationMessage(message) { root.message = message; root.busy = false }
    }
    Component.onCompleted: Qt.callLater(function() { if (root.user) password.forceActiveFocus(); else { userPopup.open(); username.forceActiveFocus() } })
}
