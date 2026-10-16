import { z } from "zod";

/** Same limits as the API password policy; the server stays the authority. */
export const PASSWORD_MIN = 12;
export const PASSWORD_MAX = 128;

export const newPasswordSchema = z
  .object({
    newPassword: z
      .string()
      .min(PASSWORD_MIN, "validation.passwordLength")
      .max(PASSWORD_MAX, "validation.passwordLength"),
    confirmation: z.string(),
  })
  .refine((value) => value.newPassword === value.confirmation, {
    message: "validation.passwordMismatch",
    path: ["confirmation"],
  });

export type NewPasswordForm = z.infer<typeof newPasswordSchema>;
