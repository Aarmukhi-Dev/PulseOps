import { afterEach, describe, expect, it, vi } from "vitest";
import { registerAccount, setAccessToken } from "./client";

const input = {
  display_name: "Pulse User",
  email: "user@example.test",
  password: "correct horse battery",
  password_confirmation: "correct horse battery",
};

afterEach(() => {
  setAccessToken(null);
  vi.unstubAllGlobals();
});

describe("registerAccount", () => {
  it("posts the registration payload and returns the login-compatible token response", async () => {
    const responseBody = {
      access_token: "signed-token",
      token_type: "bearer",
      user: { id: "user-id", email: "user@example.test", display_name: "Pulse User" },
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => responseBody,
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(registerAccount(input)).resolves.toEqual(responseBody);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/auth/register", expect.objectContaining({
      method: "POST",
      body: JSON.stringify(input),
    }));
  });

  it("surfaces a duplicate-email conflict from the API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: "An account with this email already exists" }),
    }));

    await expect(registerAccount(input)).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      message: "An account with this email already exists",
    });
  });

  it("shows safe Pydantic validation messages without request values", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: [{ msg: "Value error, Passwords do not match", input: { password: "secret" } }] }),
    }));

    await expect(registerAccount(input)).rejects.toMatchObject({ message: "Passwords do not match", status: 422 });
  });
});
