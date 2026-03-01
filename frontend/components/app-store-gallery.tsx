"use client";

import Image from "next/image";
import { motion } from "framer-motion";

export type GalleryItem = {
  title: string;
  description: string;
  src: string;
  alt: string;
};

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.1 },
  },
};

const card = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0 },
};

export function AppStoreGallery({
  sectionTitle,
  sectionDescription,
  items,
  id,
  className = "",
}: {
  sectionTitle: string;
  sectionDescription: string;
  items: GalleryItem[];
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

        {/* Equal-width grid that fills the container */}
        <motion.div
          variants={container}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-60px" }}
          className={`grid gap-5 ${items.length <= 2 ? "max-w-3xl mx-auto" : ""}`}
          style={{
            gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))`,
          }}
        >
          {items.map((item) => (
            <motion.div
              key={item.title}
              variants={card}
              className="flex flex-col rounded-2xl overflow-hidden"
              style={{
                background:
                  "linear-gradient(160deg, rgba(255,255,255,0.07) 0%, rgba(255,255,255,0.02) 100%)",
                border: "1px solid rgba(255,255,255,0.08)",
                boxShadow:
                  "0 8px 32px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.04) inset, 0 1px 0 rgba(255,255,255,0.06) inset",
              }}
            >
              {/* Top highlight */}
              <div
                className="h-px w-full shrink-0"
                style={{
                  background:
                    "linear-gradient(90deg, transparent, rgba(255,255,255,0.1) 30%, rgba(16,185,129,0.12) 50%, rgba(255,255,255,0.1) 70%, transparent)",
                }}
              />

              {/* Text */}
              <div className="px-6 pt-6 pb-4">
                <h3 className="text-lg md:text-xl font-bold text-white mb-2 tracking-tight leading-snug">
                  {item.title}
                </h3>
                <p className="text-zinc-400 text-[13px] md:text-sm leading-relaxed">
                  {item.description}
                </p>
              </div>

              {/* Screenshot */}
              <div className="relative w-full mt-auto px-4 pb-4">
                <div
                  className="relative w-full rounded-xl overflow-hidden bg-zinc-950/50"
                  style={{ aspectRatio: "9/16" }}
                >
                  <Image
                    src={item.src}
                    alt={item.alt}
                    fill
                    className="object-contain select-none pointer-events-none"
                    sizes="(max-width: 768px) 90vw, 33vw"
                  />
                </div>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
