"""设置页。DeepSeek 按官网预填，只需粘贴 API Key 并选模型。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ai.catalog import (
    PROVIDERS,
    base_url_for,
    default_model,
    models_for,
    provider_id_for,
)
from core.settings import (
    generate_peer_token,
    get_api_key,
    is_valid_peer_token,
    load_settings,
    peer_token,
    save_settings,
    set_api_key,
    set_peer_token,
)


class SettingsPage(QWidget):
    saved = Signal()
    check_update_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        s = load_settings()
        self.interval = QSpinBox()
        self.interval.setRange(8, 300)
        self.interval.setValue(int(s.get("interval_sec") or 60))
        self.ping_count = QSpinBox()
        self.ping_count.setRange(1, 20)
        self.ping_count.setValue(int(s.get("ping_count") or 2))
        self.pmtu = QCheckBox("采集时探测 PMTU（较慢）")
        self.pmtu.setChecked(bool(s.get("probe_pmtu")))
        self.v2rayn = QLineEdit(str(s.get("v2rayn_path") or ""))
        self.peer_port = QSpinBox()
        self.peer_port.setRange(1024, 65535)
        self.peer_port.setValue(int(s.get("peer_port") or 18765))
        self.peer_enable = QCheckBox("启动本机快照 HTTP 端点（仅监听 Tailscale 地址）")
        self.peer_enable.setChecked(bool(s.get("peer_server_enabled", True)))
        self.check_updates = QCheckBox("启动时检查更新（有网才访问 GitHub Release）")
        self.check_updates.setChecked(bool(s.get("check_updates", True)))
        self.btn_check_update = QPushButton("检查更新")
        self._saved_token = peer_token()
        self.token = QLineEdit(self._saved_token)
        self.token.setPlaceholderText("两台电脑填同一个令牌，才能互相看到对方状态")
        self.btn_token_new = QPushButton("生成新令牌")
        self.btn_token_copy = QPushButton("复制")

        self.ai_provider = QComboBox()
        for pid, meta in PROVIDERS.items():
            self.ai_provider.addItem(str(meta["label"]), pid)
        provider = str(s.get("ai_provider") or provider_id_for(str(s.get("ai_base_url") or ""), str(s.get("ai_model") or "")))
        idx = self.ai_provider.findData(provider)
        self.ai_provider.setCurrentIndex(max(idx, 0))

        self.ai_url = QLineEdit(str(s.get("ai_base_url") or base_url_for(provider)))
        self.ai_url.setReadOnly(True)
        self.ai_model = QComboBox()
        self.ai_model.setEditable(False)
        self.ai_key = QLineEdit(get_api_key())
        self.ai_key.setEchoMode(QLineEdit.Password)
        self.ai_key.setPlaceholderText("在 platform.deepseek.com 创建后粘贴到这里")
        self.btn_test_ai = QPushButton("测试连接")
        self.btn_save = QPushButton("保存设置")
        self.btn_save.setObjectName("primary")

        form = QFormLayout()
        form.addRow("采集周期（秒）", self.interval)
        form.addRow("每节点 ping 次数", self.ping_count)
        form.addRow("", self.pmtu)
        form.addRow("v2rayN 目录", self.v2rayn)
        form.addRow("对端快照端口", self.peer_port)
        form.addRow("", self.peer_enable)
        form.addRow("", self.check_updates)
        token_row = QHBoxLayout()
        token_row.addWidget(self.token, 1)
        token_row.addWidget(self.btn_token_new)
        token_row.addWidget(self.btn_token_copy)
        form.addRow("共享令牌", token_row)
        form.addRow("AI 服务商", self.ai_provider)
        form.addRow("接口地址（已预填）", self.ai_url)
        form.addRow("模型", self.ai_model)
        form.addRow("API Key", self.ai_key)

        root = QVBoxLayout(self)
        title = QLabel("设置")
        title.setObjectName("appTitle")
        hint = QLabel(
            "DeepSeek 已按官网配好：OpenAI 兼容接口 https://api.deepseek.com ，"
            "当前可用模型为 deepseek-flash（V4.1 Flash，推荐）和 deepseek-v4-pro。"
            "你只需粘贴 API Key、确认模型后点保存。旧模型名 deepseek-chat 已停用。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        root.addWidget(title)
        root.addWidget(hint)
        root.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_test_ai)
        row.addWidget(self.btn_check_update)
        row.addStretch()
        root.addLayout(row)
        root.addStretch()
        self.ai_provider.currentIndexChanged.connect(self._on_provider)
        self.btn_save.clicked.connect(self._save)
        self.btn_test_ai.clicked.connect(self._test_ai)
        self.btn_check_update.clicked.connect(self.check_update_requested.emit)
        self.btn_token_new.clicked.connect(lambda: self.token.setText(generate_peer_token()))
        self.btn_token_copy.clicked.connect(self._copy_token)
        self._fill_models(str(s.get("ai_model") or ""))

    def _provider(self) -> str:
        return str(self.ai_provider.currentData() or "deepseek")

    def _fill_models(self, selected: str = "") -> None:
        provider = self._provider()
        self.ai_model.blockSignals(True)
        self.ai_model.clear()
        wanted = selected or default_model(provider)
        current = 0
        for i, item in enumerate(models_for(provider)):
            self.ai_model.addItem(str(item["label"]), item["id"])
            if item["id"] == wanted:
                current = i
        self.ai_model.setCurrentIndex(current)
        self.ai_model.blockSignals(False)
        self.ai_url.setText(base_url_for(provider))
        self.ai_url.setReadOnly(provider == "deepseek")

    def _on_provider(self) -> None:
        self._fill_models()

    def _payload(self) -> dict:
        return {
            "interval_sec": self.interval.value(),
            "ping_count": self.ping_count.value(),
            "probe_pmtu": self.pmtu.isChecked(),
            "v2rayn_path": self.v2rayn.text().strip(),
            "peer_port": self.peer_port.value(),
            "peer_server_enabled": self.peer_enable.isChecked(),
            "check_updates": self.check_updates.isChecked(),
            "ai_provider": self._provider(),
            "ai_base_url": self.ai_url.text().strip() or base_url_for(self._provider()),
            "ai_model": str(self.ai_model.currentData() or default_model(self._provider())),
        }

    def _copy_token(self) -> None:
        QApplication.clipboard().setText(self.token.text().strip())
        self.btn_token_copy.setText("已复制")

    def _save_token(self) -> bool:
        value = self.token.text().strip()
        if value == self._saved_token:
            return True
        if not is_valid_peer_token(value):
            QMessageBox.warning(self, "令牌格式不对", "令牌需为 12–64 位字母、数字、下划线或连字符。")
            return False
        set_peer_token(value)
        self._saved_token = value
        return True

    def _save(self) -> None:
        if not self._save_token():
            return
        save_settings(self._payload())
        set_api_key(self.ai_key.text().strip())
        self.btn_save.setText("已保存")
        self.saved.emit()

    def _test_ai(self) -> None:
        key = self.ai_key.text().strip()
        if not key:
            QMessageBox.information(self, "还没填密钥", "请先粘贴 DeepSeek API Key。")
            return
        save_settings(self._payload())
        set_api_key(key)
        try:
            from ai.advisor import ping_model

            text = ping_model(
                base_url=self.ai_url.text().strip(),
                model=str(self.ai_model.currentData() or ""),
                api_key=key,
            )
            QMessageBox.information(self, "连接成功", "模型已接通。回复：\n" + text)
        except Exception as exc:
            QMessageBox.warning(self, "连接失败", str(exc))
