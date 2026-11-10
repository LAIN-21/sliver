import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { ExchangeIcon } from "./ExchangeIcons";
import SliverIllustration from "./SliverIllustration";

const SliverScene = lazy(() => import("./SliverScene"));
gsap.registerPlugin(ScrollTrigger);

export default function ExchangeHero() {
  const root = useRef<HTMLElement>(null);
  const progress = useRef(0);
  const [paused, setPaused] = useState(false);
  const [sceneAllowed, setSceneAllowed] = useState(false);

  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const connection = (
      navigator as Navigator & {
        connection?: EventTarget & { saveData?: boolean };
      }
    ).connection;
    const update = () =>
      setSceneAllowed(!preference.matches && !connection?.saveData);
    update();
    preference.addEventListener("change", update);
    connection?.addEventListener("change", update);
    return () => {
      preference.removeEventListener("change", update);
      connection?.removeEventListener("change", update);
    };
  }, []);

  useEffect(() => {
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      const context = gsap.context(() => {
        gsap.fromTo(
          ".hero-enter",
          { y: 22, opacity: 0 },
          {
            y: 0,
            opacity: 1,
            duration: 0.8,
            stagger: 0.07,
            ease: "power3.out",
            clearProps: "transform,opacity",
          },
        );
        ScrollTrigger.create({
          trigger: root.current,
          start: "top top",
          end: "bottom top",
          onUpdate: (self) => {
            progress.current = self.progress;
          },
        });
      }, root);
      return () => {
        context.revert();
        progress.current = 0;
      };
    });
    return () => mm.revert();
  }, []);

  return (
    <section
      className="exchange-hero"
      ref={root}
      aria-labelledby="exchange-heading"
    >
      <div className="hero-copy">
        <p className="eyebrow hero-enter">
          <span className="signal-dot" /> The agent data exchange
        </p>
        <h1 id="exchange-heading" className="hero-enter">
          Big questions.
          <br />
          <span>Small slices.</span>
        </h1>
        <p className="hero-description hero-enter">
          Give your agent the data its next answer needs. Discover useful
          datasets, quote exactly the rows that matter, and pay by the slice.
        </p>
        <div className="hero-actions hero-enter">
          <a href="#marketplace" className="button-primary">
            Explore the marketplace <ExchangeIcon name="arrow" />
          </a>
          <a href="#connect-agent" className="button-text">
            Connect your agent <ExchangeIcon name="code" size={17} />
          </a>
        </div>
        <p className="hero-proof hero-enter">
          <span>x402 payments</span>
          <span>Buyer-owned wallets</span>
          <span>XRPL Testnet</span>
        </p>
      </div>
      <div className="hero-visual hero-enter">
        <div className="hero-visual-header">
          <span className="eyebrow">One dataset. Your slice.</span>
          <button
            type="button"
            className="scene-toggle"
            disabled={!sceneAllowed}
            onClick={() => setPaused((value) => !value)}
            aria-pressed={paused}
            aria-label={
              !sceneAllowed
                ? "3D scene is static"
                : paused
                  ? "Resume 3D scene"
                  : "Pause 3D scene"
            }
          >
            <ExchangeIcon name={paused ? "play" : "pause"} size={14} />
            <span>
              {!sceneAllowed ? "Static" : paused ? "Resume" : "Pause"}
            </span>
          </button>
        </div>
        {sceneAllowed ? (
          <Suspense fallback={<SliverIllustration />}>
            <SliverScene progressRef={progress} paused={paused} />
          </Suspense>
        ) : (
          <SliverIllustration />
        )}
        <div className="hero-visual-footer">
          <div>
            <span className="schematic-label">SOURCE → SELECT → DELIVER</span>
            <p>Only what your question needs.</p>
          </div>
          <span className="visual-index">01—03</span>
        </div>
        <span className="illustration-note">
          Schematic illustration · not live activity
        </span>
      </div>
      <div className="hero-bottom">
        <p>
          Useful data. <strong>Without the whole dataset.</strong>
        </p>
        <Link to="/sell">
          Have a dataset worth sharing?{" "}
          <span>
            Become a seller <ExchangeIcon name="arrow" size={15} />
          </span>
        </Link>
      </div>
    </section>
  );
}
