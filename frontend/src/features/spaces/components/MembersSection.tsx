import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { ErrorState } from "../../../components/ui/ErrorState";
import { FormError } from "../../../components/ui/FormError";
import { Skeleton } from "../../../components/ui/Skeleton";
import { useToast } from "../../../components/ui/Toast";
import { spaceKeys, spacesApi, type Member, type SpaceRole } from "../api";

const ROLES: SpaceRole[] = ["viewer", "editor", "space_admin"];

/** Users and groups of a space with their role; changes are audited by the server. */
export function MembersSection({ spaceKey }: { spaceKey: string }) {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [newRole, setNewRole] = useState<SpaceRole>("viewer");
  const members = useQuery({
    queryKey: spaceKeys.members(spaceKey),
    queryFn: () => spacesApi.members(spaceKey),
  });
  const candidates = useQuery({
    queryKey: ["spaces", spaceKey, "principals", query],
    queryFn: () => spacesApi.principals(spaceKey, query.trim()),
    enabled: query.trim().length >= 2,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: spaceKeys.members(spaceKey) });
  const setRole = useMutation({
    mutationFn: (member: Pick<Member, "principal_type" | "principal_id"> & { role: SpaceRole }) =>
      spacesApi.setMember(spaceKey, member.principal_type, member.principal_id, member.role),
    onSuccess: async () => {
      setQuery("");
      toast(t("common.saved"));
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (member: Member) =>
      spacesApi.removeMember(spaceKey, member.principal_type, member.principal_id),
    onSuccess: refresh,
  });

  if (members.isError)
    return <ErrorState error={members.error} onRetry={() => void members.refetch()} />;
  if (members.data === undefined) return <Skeleton className="h-32 w-full" />;
  const existing = new Set(members.data.map((m) => `${m.principal_type}:${m.principal_id}`));
  const roleSelect = (value: SpaceRole, onChange: (role: SpaceRole) => void, label: string) => (
    <select
      aria-label={label}
      value={value}
      onChange={(event) => {
        onChange(event.target.value as SpaceRole);
      }}
      className="h-8 rounded-md border border-border bg-surface px-2"
    >
      {ROLES.map((role) => (
        <option key={role} value={role}>
          {t(`spaces.roles.${role}`)}
        </option>
      ))}
    </select>
  );

  return (
    <section className="space-y-3">
      <h2 className="text-base font-semibold">{t("spaces.members")}</h2>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {members.data.map((member) => (
          <li
            key={`${member.principal_type}:${member.principal_id}`}
            className="flex items-center justify-between gap-3 px-3 py-2"
          >
            <span className="flex items-center gap-2">
              {member.principal_type === "group" && (
                <Users aria-hidden className="size-4 text-text-muted" />
              )}
              <span className="font-medium">{member.name}</span>
              {member.principal_type === "group" && <Badge>{t("spaces.group")}</Badge>}
            </span>
            <span className="flex items-center gap-1">
              {roleSelect(
                member.role,
                (role) => {
                  setRole.mutate({ ...member, role });
                },
                t("spaces.roleOf", { name: member.name }),
              )}
              <Button
                variant="ghost"
                aria-label={t("spaces.removeMember", { name: member.name })}
                icon={<Trash2 aria-hidden className="size-4" />}
                onClick={() => {
                  remove.mutate(member);
                }}
              />
            </span>
          </li>
        ))}
      </ul>
      <FormError error={setRole.error ?? remove.error} />
      <div className="space-y-2">
        <label htmlFor="principal-search" className="block font-medium">
          {t("spaces.addMember")}
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <input
            id="principal-search"
            type="search"
            value={query}
            placeholder={t("spaces.searchPrincipals")}
            onChange={(event) => {
              setQuery(event.target.value);
            }}
            className="h-9 w-64 rounded-md border border-border bg-surface px-3"
          />
          {roleSelect(newRole, setNewRole, t("spaces.newMemberRole"))}
        </div>
        {candidates.data !== undefined && query.trim().length >= 2 && (
          <ul className="max-w-md divide-y divide-border rounded-md border border-border">
            {candidates.data
              .filter((p) => !existing.has(`${p.principal_type}:${p.principal_id}`))
              .map((p) => (
                <li
                  key={`${p.principal_type}:${p.principal_id}`}
                  className="flex items-center justify-between px-3 py-1.5"
                >
                  <span>
                    {p.name} {p.principal_type === "group" && <Badge>{t("spaces.group")}</Badge>}
                  </span>
                  <Button
                    variant="ghost"
                    aria-label={t("spaces.addAs", { name: p.name })}
                    icon={<UserPlus aria-hidden className="size-4" />}
                    onClick={() => {
                      setRole.mutate({ ...p, role: newRole });
                    }}
                  />
                </li>
              ))}
          </ul>
        )}
      </div>
    </section>
  );
}
