/** @odoo-module **/
// Copyright 2026 CICDoo (https://cicdoo.com)
// SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Codexoo-Commercial
// Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { AiMessageList } from "./components/message_list";
import { AiComposer } from "./components/composer";

export class AiChatAction extends Component {
    static template = "codexoo.ChatAction";
    static components = { AiMessageList, AiComposer };
    static props = ["*"];

    setup() {
        this.aiBus = useService("codexoo");
        this.notification = useService("notification");
        // Odoo 17 exposes RPC as a service (no standalone @web/core/network/rpc).
        this.rpc = useService("rpc");
        this.state = useState({
            sessions: [],
            currentId: null,
            messages: [],
            running: false,
            // Auth gate
            authenticated: false,
            authReady: false, // status check finished
            authStep: "idle", // "idle" -> "awaiting_code" (device code shown)
            authError: "",
            authUrl: "",
            authDeviceCode: "",
            authRaw: "",
        });
        this._authPoll = null;

        onWillStart(async () => {
            const { authenticated } = await this.rpc("/codexoo/auth/status");
            this.state.authenticated = authenticated;
            this.state.authReady = true;
            if (authenticated) {
                await this._initChat();
            }
        });

        onWillUnmount(() => {
            this._stopAuthPoll();
            if (this.state.currentId) {
                this.aiBus.unregister(this.state.currentId);
            }
        });
    }

    // ------------------------------------------------------------------
    // Authentication gate (Codex device-code login)
    // ------------------------------------------------------------------
    async _startAuth() {
        this.state.authError = "";
        try {
            const res = await this.rpc("/codexoo/auth/start");
            if (res.authenticated) {
                await this._onAuthenticated();
                return;
            }
            this.state.authUrl = res.url || "";
            this.state.authDeviceCode = res.code || "";
            this.state.authRaw = res.raw || "";
            this.state.authStep = "awaiting_code";
            // Open the verification page in a new tab when we have a URL.
            if (res.url) {
                browser.open(res.url, "_blank", "noopener,noreferrer");
            }
            // Poll the server until codex finishes writing the credentials.
            this._startAuthPoll();
        } catch (e) {
            // Odoo JSON-RPC errors carry the real message in e.data.message
            // (e.message is the generic "Odoo Server Error").
            this.state.authError =
                e.data?.message || e.message || "Could not start the login.";
        }
    }

    _startAuthPoll() {
        this._stopAuthPoll();
        this._authPoll = browser.setInterval(async () => {
            try {
                const { authenticated } = await this.rpc("/codexoo/auth/status");
                if (authenticated) {
                    this._stopAuthPoll();
                    await this._onAuthenticated();
                }
            } catch {
                // transient; keep polling
            }
        }, 2500);
    }

    _stopAuthPoll() {
        if (this._authPoll) {
            browser.clearInterval(this._authPoll);
            this._authPoll = null;
        }
    }

    async _onAuthenticated() {
        this.state.authenticated = true;
        this.state.authStep = "idle";
        this.state.authUrl = "";
        this.state.authDeviceCode = "";
        await this._initChat();
    }

    async _initChat() {
        await this._loadSessions();
        if (!this.state.sessions.length) {
            await this._newSession();
        } else {
            await this._openSession(this.state.sessions[0].id);
        }
    }

    async _loadSessions() {
        this.state.sessions = await this.rpc("/codexoo/sessions");
    }

    async _newSession() {
        const s = await this.rpc("/codexoo/new");
        this.state.sessions.unshift(s);
        await this._openSession(s.id);
    }

    async _openSession(id) {
        if (this.state.currentId) {
            this.aiBus.unregister(this.state.currentId);
        }
        this.state.currentId = id;
        this.aiBus.register(id, (p) => this._onBusEvent(p));
        const data = await this.rpc("/codexoo/messages", { session_id: id });
        this.state.messages = data.messages;
        this.state.running = data.state === "running";
    }

    _upsertMessage(msg) {
        const idx = this.state.messages.findIndex((m) => m.id === msg.id);
        if (idx === -1) {
            this.state.messages.push(msg);
        } else {
            this.state.messages[idx] = msg;
        }
    }

    _onBusEvent(p) {
        switch (p.kind) {
            case "started":
                this.state.running = true;
                break;
            case "message":
                this._upsertMessage(p.message);
                break;
            case "done":
                this.state.running = false;
                this._reload();
                break;
            case "error":
                this.state.running = false;
                this.state.messages.push({
                    id: `err-${Date.now()}`,
                    role: "error",
                    body: p.error || "Something went wrong.",
                    tool_calls: [],
                });
                break;
        }
    }

    async _reload() {
        if (!this.state.currentId) return;
        const data = await this.rpc("/codexoo/messages", {
            session_id: this.state.currentId,
        });
        this.state.messages = data.messages;
    }

    async onSend(text, files = []) {
        // Optimistic user bubble; the assistant reply arrives over the bus.
        this.state.messages.push({
            id: `tmp-${Date.now()}`,
            role: "user",
            body: text,
            tool_calls: [],
            attachments: files,
        });
        this.state.running = true;
        try {
            await this.rpc("/codexoo/send", {
                session_id: this.state.currentId,
                body: text,
                attachment_ids: files.map((f) => f.id),
            });
        } catch (e) {
            this.state.running = false;
            this.notification.add(e.data?.message || e.message || "Failed to send.", {
                type: "danger",
            });
        }
    }

    async onStop() {
        await this.rpc("/codexoo/stop", { session_id: this.state.currentId });
        this.state.running = false;
    }
}

registry.category("actions").add("codexoo.chat", AiChatAction);
