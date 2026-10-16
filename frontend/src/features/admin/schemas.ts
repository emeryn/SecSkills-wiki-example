import { z } from "zod";

/** Mirrors backend/app/schemas/admin.py; the server stays the authority. */
export const userFormSchema = z.object({
  username: z
    .string()
    .trim()
    .min(2, "validation.required")
    .max(64)
    .regex(/^[A-Za-z0-9._-]+$/, "validation.username"),
  email: z.union([z.literal(""), z.email("validation.email").max(254)]),
  display_name: z.string().trim().max(100),
  role: z.enum(["user", "admin"]),
});

export const userEditSchema = userFormSchema.extend({ status: z.enum(["active", "disabled"]) });

export const groupFormSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "validation.required")
    .max(100)
    .regex(/^[^\r\n<>]+$/, "validation.groupName"),
  description: z.string().trim().max(500),
});

export type UserForm = z.infer<typeof userFormSchema>;
export type UserEditForm = z.infer<typeof userEditSchema>;
export type GroupForm = z.infer<typeof groupFormSchema>;
