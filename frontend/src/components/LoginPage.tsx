// 账号体系登录/注册页（Phase 2 多用户）：
// Given 未登录 When 访问 Then 登录页；登录/注册成功后 cookie 已由后端 Set-Cookie，回调 onSuccess
import { useState } from "react";
import { Alert, Button, Card, Form, Input, Typography } from "antd";
import { apiPost } from "../api/client";

const { Title } = Typography;

interface Me {
  username: string;
  display_name: string | null;
  is_admin: boolean;
}

export function LoginPage({ onSuccess }: { onSuccess: (me: Me) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (values: { username: string; password: string }) => {
    setError(null);
    setPending(true);
    try {
      const me = await apiPost<Me>(`/auth/${mode}`, {
        username: values.username,
        password: values.password,
      });
      onSuccess(me);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg.includes("401") || msg.includes("409") ? "用户名或密码错误（或用户名已存在）" : msg);
    } finally {
      setPending(false);
    }
  };

  return (
    <div style={{ maxWidth: 380, margin: "80px auto" }}>
      <Card>
        <Title level={4} style={{ marginTop: 0 }}>
          {mode === "login" ? "登录 CS2HQ" : "注册新账号"}
        </Title>
        {error ? <Alert type="error" message={error} style={{ marginBottom: 16 }} /> : null}
        <Form layout="vertical" onFinish={submit}>
          <Form.Item name="username" rules={[{ required: true, message: "请输入用户名" }]}>
            <Input placeholder="用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: "请输入密码" }]}>
            <Input.Password placeholder="密码" autoComplete={mode === "login" ? "current-password" : "new-password"} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={pending}>
            {mode === "login" ? "登录" : "注册"}
          </Button>
        </Form>
        <a
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
          style={{ display: "inline-block", marginTop: 12 }}
        >
          {mode === "login" ? "注册新账号" : "已有账号？去登录"}
        </a>
      </Card>
    </div>
  );
}
