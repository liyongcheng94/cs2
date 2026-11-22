// 完美平台短信登录：手机号 → WanmeiCaptcha 滑块（用户自己完成，不做自动化）→ 短信码 → token 加密入库
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Input, message, Space, Tag } from "antd";
import { apiGet, apiPost } from "../api/client";

declare global {
  interface Window {
    WanmeiCaptcha?: any;
  }
}

const CAPTCHA_JS = "https://cstatic.games.wanmei.com/captchas/ai/js/wanmeiCaptcha.min.js";

function loadScript(src: string): Promise<void> {
  if (window.WanmeiCaptcha) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("验证码组件加载失败"));
    document.head.appendChild(s);
  });
}

interface LoginStatus {
  logged_in: boolean;
  steam_id: string | null;
  phone: string | null;
}

export function WanmeiLogin() {
  const [phone, setPhone] = useState("");
  const [smsCode, setSmsCode] = useState("");
  const [countdown, setCountdown] = useState(0);
  const [sending, setSending] = useState(false);
  const [logging, setLogging] = useState(false);
  const captchaRef = useRef<any>(null);
  const capTicketRef = useRef<string>("");
  const sendBtnId = "j-cs2hq-sendcode";
  const status = useQuery({
    queryKey: ["wanmei-status"],
    queryFn: () => apiGet<LoginStatus>("/wanmei/status"),
  });

  useEffect(() => {
    const t = setInterval(() => setCountdown((c) => (c > 0 ? c - 1 : 0)), 1000);
    return () => clearInterval(t);
  }, []);

  const resetCaptcha = () => {
    const container = document.getElementById("pwcaptchas-container");
    if (container) container.innerHTML = "";
    captchaRef.current = null;
  };

  const initCaptcha = async (capTicket: string) => {
    await loadScript(CAPTCHA_JS);
    resetCaptcha();
    capTicketRef.current = capTicket;
    const m = new window.WanmeiCaptcha({ containerId: "pwcaptchas-container" });
    m.init({
      appId: "20041", // partner 门户同款验证码 appId
      capTicket,
      capType: "popup",
      bindBtn: `#${sendBtnId}`,
      zoom: 1,
      initCallback: () => {
        // 绑定完成后唤起滑块（用户本次点击已被前端处理消费）
        document.getElementById(sendBtnId)?.click();
      },
      callback: () => {
        const secCode = m.getValidateResult();
        void doSendCode(secCode);
      },
    });
    captchaRef.current = m;
  };

  const doSendCode = async (secCode: string) => {
    try {
      await apiPost("/wanmei/send-code", {
        mobile_phone: phone,
        sec_code: secCode,
        cap_ticket: capTicketRef.current,
      });
      message.success("验证码已发送，注意查收短信");
      setCountdown(60);
    } catch (e: any) {
      message.error(`发送失败：${e.message ?? e}`);
    } finally {
      resetCaptcha();
      setSending(false);
    }
  };

  const onSendClick = async () => {
    if (!/^1\d{10}$/.test(phone)) {
      message.warning("请输入正确的 11 位手机号");
      return;
    }
    setSending(true);
    try {
      const init = await apiPost<{ capTicket: string }>("/wanmei/captcha-init");
      await initCaptcha(init.capTicket);
      // 组件以 bindBtn 弹出：初始化完成后模拟一次点击唤起滑块
      document.getElementById(sendBtnId)?.click();
    } catch (e: any) {
      message.error(`初始化验证码失败：${e.message ?? e}`);
      setSending(false);
    }
  };

  const onLogin = async () => {
    setLogging(true);
    try {
      const out = await apiPost<{ steam_id: string }>("/wanmei/sms-login", {
        mobile_phone: phone,
        security_code: smsCode,
      });
      message.success(`登录成功：steamId ${out.steam_id}`);
      setSmsCode("");
      status.refetch();
    } catch (e: any) {
      message.error(`登录失败：${e.message ?? e}`);
    } finally {
      setLogging(false);
    }
  };

  const st = status.data;
  return (
    <Card title="完美平台账号（短信登录）" style={{ maxWidth: 640 }}>
      {st?.logged_in ? (
        <Space direction="vertical">
          <Space>
            <Tag color="green">已登录</Tag>
            <span>steamId: {st.steam_id}</span>
            {st.phone ? <Tag>手机尾号 {st.phone.slice(-4)}</Tag> : null}
          </Space>
          <span style={{ color: "#999", fontSize: 12 }}>
            token 已加密存储；失效时任务会熔断为 NEED_AUTH 并在此页提示重登。
          </span>
        </Space>
      ) : (
        <Space direction="vertical" style={{ width: "100%" }}>
          <Input
            placeholder="完美平台绑定手机号"
            value={phone}
            maxLength={11}
            onChange={(e) => setPhone(e.target.value)}
          />
          <Space>
            <Button
              id={sendBtnId}
              loading={sending}
              disabled={countdown > 0}
              onClick={onSendClick}
            >
              {countdown > 0 ? `${countdown}s 后重试` : "发送验证码"}
            </Button>
            <div id="pwcaptchas-container" />
          </Space>
          <Space>
            <Input
              placeholder="6 位短信验证码"
              value={smsCode}
              maxLength={6}
              style={{ width: 160 }}
              onChange={(e) => setSmsCode(e.target.value)}
            />
            <Button type="primary" loading={logging} onClick={onLogin}>
              登录
            </Button>
          </Space>
          <span style={{ color: "#999", fontSize: 12 }}>
            登录走完美官方 passport 接口（与 partner 门户同款），滑块由你本人完成，本平台不做任何自动化验证。
          </span>
        </Space>
      )}
    </Card>
  );
}
