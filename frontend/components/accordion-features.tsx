"use client";

import Image from "next/image";
import { motion, useScroll, useTransform } from "framer-motion";
import { useRef } from "react";

export type AccordionFeature = {
  title: string;
  description: string;
  src: string;
  alt: string;
};

export function AccordionFeatureSection({
  sectionTitle,
  sectionDescription,
  features,
  id,
  className = "",
}: {
  sectionTitle: string;
  sectionDescription: string;
  features: AccordionFeature[];
  id?: string;
  className?: string;
}) {
  return (
    <section
      id={id}
      className={`py-20 sm:py-28 border-t border-zinc-800/80 scroll-mt-20 ${className}`}
    >
      <div className="container mx-auto w-full max-w-6xl px-4 min-w-0">
        <motion.h2
          initial={{ opacity: 0, y: 12 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-2xl sm:text-4xl font-bold text-white mb-4"
        >
          {sectionTitle}
        </motion.h2>
        <motion.p
          initial={{ opacity: 0, y: 12 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-zinc-400 text-lg mb-14 max-w-xl"
        >
          {sectionDescription}
        </motion.p>

        <div className="relative">
          {features.map((feature, i) => (
            <StickyCard
              key={feature.title}
              feature={feature}
              index={i}
              total={features.length}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

function StickyCard({
  feature,
  index,
  total,
}: {
  feature: AccordionFeature;
  index: number;
  total: number;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: cardRef,
    offset: ["start end", "end start"],
  });

  const isLast = index === total - 1;
  const scale = useTransform(
    scrollYProgress,
    [0, 0.5, 1],
    isLast ? [1, 1, 1] : [1, 1, 0.93]
  );

  const stickyTop = 80 + index * 16;

  return (
    <div
      ref={cardRef}
      className="h-[50vh] md:h-[55vh]"
      style={{ marginBottom: isLast ? 0 : "-5vh" }}
    >
      <motion.div
        className="sticky overflow-hidden rounded-2xl"
        style={{
          top: stickyTop,
          scale,
          zIndex: index + 1,
          transformOrigin: "top center",
          background:
            "linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.02) 50%, rgba(255,255,255,0.04) 100%)",
          backdropFilter: "blur(24px) saturate(1.4)",
          WebkitBackdropFilter: "blur(24px) saturate(1.4)",
          border: "1px solid rgba(255,255,255,0.08)",
          boxShadow: [
            "0 8px 32px rgba(0,0,0,0.4)",
            "0 0 0 1px rgba(255,255,255,0.04) inset",
            "0 1px 0 rgba(255,255,255,0.06) inset",
          ].join(", "),
        }}
      >
        {/* Glass highlight shimmer along the top edge */}
        <div
          className="absolute top-0 left-0 right-0 h-px pointer-events-none"
          style={{
            background:
              "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.12) 30%, rgba(16,185,129,0.15) 50%, rgba(255,255,255,0.12) 70%, transparent 100%)",
          }}
        />

        <div className="grid grid-cols-1 md:grid-cols-[2fr_3fr] gap-0">
          {/* Text: ~40% width */}
          <div className="flex flex-col justify-center px-6 py-6 md:px-10 md:py-8">
            <h3 className="text-lg md:text-2xl font-semibold text-white mb-2">
              {feature.title}
            </h3>
            <p className="text-zinc-400 text-sm md:text-[15px] leading-relaxed">
              {feature.description}
            </p>
          </div>
          {/* Image: ~60% width, full portrait visible */}
          <div
            className="relative w-full h-[360px] md:h-[420px] border-t md:border-t-0 md:border-l overflow-hidden flex items-center justify-center p-4"
            style={{ borderColor: "rgba(255,255,255,0.06)" }}
          >
            <Image
              src={feature.src}
              alt={feature.alt}
              fill
              className="object-contain select-none pointer-events-none"
              sizes="(max-width: 768px) 100vw, 60vw"
            />
            <div
              className="absolute inset-0 pointer-events-none"
              style={{
                background:
                  "linear-gradient(180deg, rgba(255,255,255,0.03) 0%, transparent 30%, transparent 70%, rgba(0,0,0,0.15) 100%)",
              }}
            />
          </div>
        </div>
      </motion.div>
    </div>
  );
}
