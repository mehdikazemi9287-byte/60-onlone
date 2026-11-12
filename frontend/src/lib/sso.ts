/**
 * ورود مشترک 60online.ir → vambi.ir (backend: POST /api/v1/auth/sso/issue, see backend/app/services/sso_service.py).
 *
 * 60online is only the identity side: a signed-in user, after an explicit click on /sso/vambi, asks the server for a
 * 60-second one-time code for an allow-listed sister origin and is sent to `<origin>/sso/callback`. The sister site
 * swaps the code server-to-server at /api/v1/auth/sso/exchange (with its Origin header). Ported from PR #19 (SSO only).
 */
import { apiRequest } from "@/lib/api";

export const sso = {
  issue: (token: string, target_origin: string, state: string) =>
    apiRequest<{ redirect_url: string; expires_in: number }>("/auth/sso/issue", {
      method: "POST", token, body: JSON.stringify({ target_origin, state }),
    }),
};
