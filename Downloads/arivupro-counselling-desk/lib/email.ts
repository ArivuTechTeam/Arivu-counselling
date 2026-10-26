// Email sending via Gmail SMTP using nodemailer-style fetch approach.
// Cloudflare Workers don't support Node net/tls, so we use the Gmail REST API
// via OAuth2 or, simpler for this setup, Gmail's SMTP-over-fetch workaround.
// For Cloudflare Workers the recommended approach is an HTTP email service
// (Resend, SendGrid, Mailgun). This module uses Resend if RESEND_API_KEY is set,
// falling back to a console draft (dev mode).

export interface EmailPayload {
  to: string;
  subject: string;
  html: string;
  text: string;
}

export async function sendEmail(payload: EmailPayload): Promise<{ok:boolean;error?:string}> {
  const key = process.env.RESEND_API_KEY;

  // If no key configured, log draft to console (dev / missing config)
  if (!key) {
    console.log('[Email draft – configure RESEND_API_KEY to send]\n', JSON.stringify(payload, null, 2));
    return {ok: true};
  }

  try {
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', Authorization: `Bearer ${key}`},
      body: JSON.stringify({
        from: `ArivuPro Counselling <${process.env.SMTP_USER || 'noreply@arivupro.com'}>`,
        to: [payload.to],
        subject: payload.subject,
        html: payload.html,
        text: payload.text,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({})) as {message?: string};
      return {ok: false, error: err.message || 'Email send failed.'};
    }
    return {ok: true};
  } catch (e) {
    return {ok: false, error: (e as Error).message};
  }
}

export function studentConfirmationEmail(data: {
  name: string;
  course: string;
  level: string;
  slot: string;
  concern: string;
  referenceId: string;
}): EmailPayload {
  const slotDisplay = data.slot || 'To be confirmed';

  const html = `
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f7f9f7;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f7f9f7;padding:40px 20px">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e0e8e1;max-width:600px;width:100%">
        <tr>
          <td style="background:#214c39;padding:28px 36px">
            <span style="font-size:22px;font-weight:800;color:#fff;letter-spacing:-1px">arivu<span style="color:#f0d98b">pro</span></span>
            <span style="display:block;font-size:10px;letter-spacing:2px;color:#b4c8bc;margin-top:4px">COUNSELLING DESK</span>
          </td>
        </tr>
        <tr>
          <td style="padding:36px">
            <h2 style="font-size:22px;color:#214c39;margin:0 0 8px">Your counselling session is confirmed</h2>
            <p style="color:#6e8675;font-size:14px;margin:0 0 28px">Hi ${data.name}, we've received your request and are looking forward to speaking with you.</p>

            <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f8f3;border-radius:8px;padding:20px;margin-bottom:24px">
              <tr><td style="padding:6px 0"><span style="font-size:11px;color:#8a9a8d;font-weight:600;letter-spacing:.5px">COURSE</span><br><strong style="color:#214c39">${data.course} · ${data.level}</strong></td></tr>
              <tr><td style="padding:6px 0"><span style="font-size:11px;color:#8a9a8d;font-weight:600;letter-spacing:.5px">SCHEDULED TIME</span><br><strong style="color:#214c39">${slotDisplay} IST</strong></td></tr>
              <tr><td style="padding:6px 0"><span style="font-size:11px;color:#8a9a8d;font-weight:600;letter-spacing:.5px">YOUR QUERY</span><br><span style="color:#3d5544;font-size:13px">${data.concern}</span></td></tr>
              <tr><td style="padding:6px 0"><span style="font-size:11px;color:#8a9a8d;font-weight:600;letter-spacing:.5px">REFERENCE</span><br><code style="color:#2e8857;font-size:13px">${data.referenceId.slice(0,8).toUpperCase()}</code></td></tr>
            </table>

            <div style="background:#fffbea;border:1px solid #e3d9b5;border-radius:8px;padding:16px;margin-bottom:24px">
              <strong style="color:#7c6e2a;font-size:12px">What happens next?</strong>
              <ul style="margin:8px 0 0;padding-left:18px;color:#7c6e2a;font-size:12px;line-height:1.9">
                <li>Our counselling team will review your query.</li>
                <li>You'll receive a Google Meet link before the session.</li>
                <li>The session is up to 30 minutes at your scheduled time.</li>
              </ul>
            </div>

            <p style="font-size:12px;color:#819087">Questions before your session? Email us at <a href="mailto:marketing@arivupro.com" style="color:#2e8857">marketing@arivupro.com</a></p>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 36px;background:#f5f8f3;border-top:1px solid #e4ede4">
            <p style="margin:0;font-size:11px;color:#8a9a8d">ArivuPro Academy · Student Counselling · <a href="mailto:marketing@arivupro.com" style="color:#2e8857">marketing@arivupro.com</a></p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>`;

  const text = `Hi ${data.name},\n\nYour ArivuPro counselling session is confirmed.\n\nCourse: ${data.course} · ${data.level}\nScheduled: ${slotDisplay} IST\nQuery: ${data.concern}\nReference: ${data.referenceId.slice(0,8).toUpperCase()}\n\nOur team will send you a Google Meet link before the session.\n\nQuestions? Email marketing@arivupro.com\n\nArivuPro Academy`;

  return {
    to: '',
    subject: `Your ArivuPro counselling session is confirmed`,
    html,
    text,
  };
}

export function adminNotificationEmail(data: {
  studentName: string;
  studentEmail: string;
  studentPhone: string;
  course: string;
  level: string;
  slot: string;
  concern: string;
  referenceId: string;
}): EmailPayload {
  const slotDisplay = data.slot || 'No slot selected';

  const html = `
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f7f9f7;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f7f9f7;padding:40px 20px">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e0e8e1;max-width:600px;width:100%">
        <tr>
          <td style="background:#214c39;padding:28px 36px">
            <span style="font-size:22px;font-weight:800;color:#fff;letter-spacing:-1px">arivu<span style="color:#f0d98b">pro</span></span>
            <span style="display:block;font-size:10px;letter-spacing:2px;color:#b4c8bc;margin-top:4px">NEW COUNSELLING REQUEST</span>
          </td>
        </tr>
        <tr>
          <td style="padding:36px">
            <h2 style="font-size:20px;color:#214c39;margin:0 0 6px">New counselling request — action required</h2>
            <p style="color:#6e8675;font-size:13px;margin:0 0 24px">A student has submitted a counselling request via the ArivuPro Counselling Desk.</p>

            <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f8f3;border-radius:8px;padding:20px;margin-bottom:24px">
              <tr><td style="padding:6px 0"><span style="font-size:11px;color:#8a9a8d;font-weight:600">STUDENT NAME</span><br><strong style="color:#214c39">${data.studentName}</strong></td></tr>
              <tr><td style="padding:6px 0"><span style="font-size:11px;color:#8a9a8d;font-weight:600">EMAIL</span><br><a href="mailto:${data.studentEmail}" style="color:#2e8857">${data.studentEmail}</a></td></tr>
              <tr><td style="padding:6px 0"><span style="font-size:11px;color:#8a9a8d;font-weight:600">PHONE</span><br><a href="tel:${data.studentPhone}" style="color:#2e8857">${data.studentPhone}</a></td></tr>
              <tr><td style="padding:6px 0"><span style="font-size:11px;color:#8a9a8d;font-weight:600">COURSE / LEVEL</span><br><strong style="color:#214c39">${data.course} · ${data.level}</strong></td></tr>
              <tr><td style="padding:6px 0"><span style="font-size:11px;color:#8a9a8d;font-weight:600">PREFERRED SLOT</span><br><strong style="color:#214c39">${slotDisplay} IST</strong></td></tr>
              <tr><td style="padding:6px 0"><span style="font-size:11px;color:#8a9a8d;font-weight:600">QUERY</span><br><span style="color:#3d5544;font-size:13px;line-height:1.7">${data.concern}</span></td></tr>
              <tr><td style="padding:6px 0"><span style="font-size:11px;color:#8a9a8d;font-weight:600">REFERENCE</span><br><code style="color:#2e8857">${data.referenceId.slice(0,8).toUpperCase()}</code></td></tr>
            </table>

            <div style="background:#eaf4ed;border-radius:8px;padding:16px;margin-bottom:20px">
              <strong style="color:#214c39;font-size:12px">Next steps for the counsellor</strong>
              <ol style="margin:8px 0 0;padding-left:18px;color:#3d5544;font-size:12px;line-height:1.9">
                <li>Open the admin dashboard and confirm this request.</li>
                <li>Add a Google Meet link to the session.</li>
                <li>Send the Meet link to the student before the session time.</li>
              </ol>
            </div>

            <a href="mailto:${data.studentEmail}?subject=Your%20ArivuPro%20Counselling%20Session&body=Hi%20${encodeURIComponent(data.studentName)}%2C%0A%0AThank%20you%20for%20requesting%20a%20counselling%20session.%20Here%20is%20your%20Google%20Meet%20link%3A%0A%0A[ADD%20MEET%20LINK%20HERE]%0A%0ASession%20time%3A%20${encodeURIComponent(slotDisplay)}%20IST%0A%0ASee%20you%20then!%0AArivuPro%20Counselling%20Team"
              style="display:inline-block;background:#2e8857;color:#fff;padding:12px 20px;border-radius:7px;text-decoration:none;font-size:12px;font-weight:600">
              Reply to student with Meet link →
            </a>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 36px;background:#f5f8f3;border-top:1px solid #e4ede4">
            <p style="margin:0;font-size:11px;color:#8a9a8d">ArivuPro Academy · Internal counselling notification</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>`;

  const text = `New counselling request — ArivuPro\n\nStudent: ${data.studentName}\nEmail: ${data.studentEmail}\nPhone: ${data.studentPhone}\nCourse: ${data.course} · ${data.level}\nSlot: ${slotDisplay} IST\nQuery: ${data.concern}\nReference: ${data.referenceId.slice(0,8).toUpperCase()}\n\nOpen the admin dashboard to confirm and add a Google Meet link.`;

  return {
    to: '',
    subject: `New counselling request — ${data.studentName} · ${data.course}`,
    html,
    text,
  };
}
