/**
 * Renders text as individual <span class="apl-char"> letters so GSAP can
 * animate them one-by-one (the headline reveal). `em` styles them as the
 * italic accent word.
 */
export function SplitText({ text, em }: { text: string; em?: boolean }) {
  return (
    <>
      {text.split("").map((ch, i) => (
        <span
          key={i}
          className={`apl-char${em ? " apl-em" : ""}`}
          style={{ display: "inline-block" }}
        >
          {ch === " " ? " " : ch}
        </span>
      ))}
    </>
  );
}
