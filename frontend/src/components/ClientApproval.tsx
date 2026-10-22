import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, FileSignature } from "lucide-react";
import { api } from "../api/client";
import { FiguresTable } from "../pages/FilingPage";
import { Badge, Button, Callout, Card } from "../ui";
import { fmtDateTime } from "../format";

/** The taxpayer's approval + Form 8879 signature. Shown on the client surface only. */
export function ClientApproval() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["client-filing"], queryFn: api.clientFiling });
  const [pin, setPin] = useState("");
  const [agree, setAgree] = useState(false);
  const sign = useMutation({ mutationFn: () => api.clientApprove(pin, agree), onSuccess: () => qc.invalidateQueries({ queryKey: ["client-filing"] }) });
  const d = q.data;
  if (!d || !d.presented) return null;
  return (
    <Card title="Your 2025 return is ready for approval"
      actions={d.filed ? <Badge tone="verified">Filed {d.accepted_at?.slice(0, 10)}</Badge> : d.you_signed ? <Badge tone="verified" icon={<BadgeCheck aria-hidden />}>You signed</Badge> : <Badge tone="warning">Action needed</Badge>}>
      <div className="stack-3">
        {d.figures && <FiguresTable f={d.figures} caption={`Presented ${d.presented_at ? fmtDateTime(d.presented_at) : ""}. These are the amounts on Form 8879 / FTB 8879.`} />}
        {!d.current && <Callout tone="warning">The firm changed the return after presenting it; you'll be asked to approve the new version.</Callout>}
        {d.you_signed ? (
          <Callout tone="neutral">You approved and signed {d.signed_at ? fmtDateTime(d.signed_at) : ""}.{d.others_signed.length ? ` Also signed: ${d.others_signed.join(", ")}.` : " Waiting for your spouse."}</Callout>
        ) : d.current && (
          <div className="stack-2">
            <label className="row text-sm"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
              I have reviewed the return and, to the best of my knowledge, it is true, correct and complete. I authorize Miraflores to file it electronically.</label>
            <div className="finding__actions">
              <input className="ui-input review__input--short" inputMode="numeric" maxLength={5} placeholder="5-digit PIN" value={pin}
                onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} aria-label="Self-select signature PIN" />
              <Button variant="primary" icon={<FileSignature aria-hidden />} disabled={!agree || pin.length !== 5 || sign.isPending} onClick={() => sign.mutate()}>Approve & sign Form 8879</Button>
            </div>
            <p className="text-tertiary text-xs">Your PIN is your electronic signature. The firm stores only a one-way hash of it.</p>
            {sign.error && <Callout tone="error">{sign.error.message}</Callout>}
          </div>
        )}
      </div>
    </Card>
  );
}
