import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { ExchangeIcon, SliverMark } from "./ExchangeIcons";

const INSTALL =
  'claude mcp add sliver -- uvx --from "git+https://github.com/LAIN-21/sliver#subdirectory=packages/sliver-mcp" sliver-mcp';
const STEPS = [
  {
    number: "01",
    title: "Find the missing piece.",
    body: "Search public listings by coverage, schema and price. Your agent evaluates whether the data fits the question.",
    detail: "sliver_search → sliver_evaluate",
  },
  {
    number: "02",
    title: "Make the cut.",
    body: "Choose a listed sliver or quote a custom slice by date and category. A quote costs nothing. Your agent owns the spending decision.",
    detail: "sliver_quote_slice → human decision",
  },
  {
    number: "03",
    title: "Pay. Verify. Put it to work.",
    body: "Your agent signs locally. Sliver checks the XRPL Testnet payment and delivers the immutable CSV, ready for a SHA-256 check.",
    detail: "sliver_buy → verified bytes",
  },
];

export default function ExchangeProtocol() {
  const section = useRef<HTMLElement>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">(
    "idle",
  );
  useEffect(() => {
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      const context = gsap.context(() => {
        gsap.utils.toArray<HTMLElement>(".protocol-beat").forEach((beat) => {
          gsap.fromTo(
            beat.querySelector(".protocol-copy"),
            { y: 22, opacity: 0.55 },
            {
              y: 0,
              opacity: 1,
              ease: "none",
              scrollTrigger: {
                trigger: beat,
                start: "top 85%",
                end: "top 45%",
                scrub: true,
              },
            },
          );
          gsap.fromTo(
            beat.querySelector(".protocol-plate"),
            { rotateX: 42, rotateZ: -14, y: 24 },
            {
              rotateX: 18,
              rotateZ: -6,
              y: -12,
              ease: "none",
              scrollTrigger: {
                trigger: beat,
                start: "top bottom",
                end: "bottom top",
                scrub: true,
              },
            },
          );
        });
        ScrollTrigger.refresh();
      }, section);
      return () => context.revert();
    });
    return () => mm.revert();
  }, []);
  async function copy() {
    try {
      await navigator.clipboard.writeText(INSTALL);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }
  return (
    <section
      className="exchange-protocol"
      ref={section}
      id="connect-agent"
      aria-labelledby="protocol-heading"
    >
      <div className="protocol-heading">
        <p className="eyebrow">Built for the way agents work</p>
        <h2 id="protocol-heading">
          From a missing fact
          <br />
          to a better answer.
        </h2>
        <p>Small purchases. Clear decisions. Data you can verify.</p>
        <a href="#agent-install" className="button-light">
          Get the Sliver MCP <ExchangeIcon name="arrow" />
        </a>
      </div>
      <div className="protocol-sequence">
        {STEPS.map((step) => (
          <article className="protocol-beat" key={step.number}>
            <div className="protocol-copy">
              <span className="protocol-number">/{step.number}</span>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
              <code>{step.detail}</code>
            </div>
            <div
              className={`protocol-plate plate-${step.number}`}
              aria-hidden="true"
            >
              <SliverMark />
              <div />
              <div />
              <div />
              <span>
                {step.number === "03"
                  ? "SHA-256 / VERIFIED"
                  : step.number === "02"
                    ? "CUSTOM SLICE / QUOTED"
                    : "METADATA / DISCOVERED"}
              </span>
            </div>
          </article>
        ))}
      </div>
      <div className="agent-install" id="agent-install">
        <div>
          <span className="eyebrow">Your agent. Your wallet. Your call.</span>
          <h3>
            One connection.
            <br />A new source of answers.
          </h3>
          <p>
            Install the free Sliver MCP in Claude Code. For other clients and
            wallet setup, see the{" "}
            <a
              href="https://github.com/LAIN-21/sliver/tree/main/packages/sliver-mcp#readme"
              target="_blank"
              rel="noreferrer"
            >
              MCP documentation ↗
            </a>
            .
          </p>
        </div>
        <div className="install-command">
          <div>
            <span>CLAUDE CODE / TERMINAL</span>
            <button
              type="button"
              onClick={() => void copy()}
              aria-label="Copy MCP install command"
            >
              <ExchangeIcon
                name={copyState === "copied" ? "check" : "copy"}
                size={16}
              />
              {copyState === "copied" ? "Copied" : "Copy"}
            </button>
          </div>
          <pre tabIndex={0}>
            <code>{INSTALL}</code>
          </pre>
          <p role="status">
            {copyState === "failed"
              ? "Clipboard unavailable. Select and copy the command above."
              : "Testnet only. Set your wallet and budget in your own agent."}
          </p>
        </div>
      </div>
      <div className="protocol-end">
        <Link to="/activity">
          See the purchase activity <ExchangeIcon name="arrow" size={17} />
        </Link>
        <a href="#marketplace">Back to the marketplace ↑</a>
      </div>
    </section>
  );
}
