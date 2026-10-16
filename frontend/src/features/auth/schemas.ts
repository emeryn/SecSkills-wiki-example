import { z } from "zod";

export { newPasswordSchema, type NewPasswordForm } from "../../lib/password-schema";

export const loginSchema = z.object({
  username: z
    .string()
    .trim()
    .min(2, "validation.required")
    .max(64)
    .regex(/^[A-Za-z0-9._-]+$/, "validation.username"),
  password: z.string().min(1, "validation.required").max(1024),
});

export const codeSchema = z.object({
  code: z.string().trim().min(6, "validation.code").max(32, "validation.code"),
});

export const resetRequestSchema = z.object({
  email: z.email("validation.email").max(254),
});

export type LoginForm = z.infer<typeof loginSchema>;
export type CodeForm = z.infer<typeof codeSchema>;
export type ResetRequestForm = z.infer<typeof resetRequestSchema>;
