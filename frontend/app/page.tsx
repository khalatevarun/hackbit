"use client";

import Image from "next/image";
import { motion } from "framer-motion";
import { AppStoreGallery } from "@/components/app-store-gallery";

const TELEGRAM_URL = "https://t.me/hackbitz_bot";

function HackbitzLogo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-baseline font-semibold tracking-tight ${className}`} style={{ fontFamily: "var(--font-plus-jakarta)" }}>
      <span className="text-white">Hack</span>
      <span className="italic text-emerald-400">bit</span>
      <span className="text-white">z</span>
    </span>
  );
}

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.06 },
  },
};

const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0 },
};

function ExaLogo({ className }: { className?: string }) {
  return (
    <motion.a
      href="https://exa.ai"
      target="_blank"
      rel="noopener noreferrer"
      className={`relative h-10 w-28 shrink-0 block ${className ?? ""}`}
      aria-label="Exa"
      whileHover={{ scale: 1.08, opacity: 1 }}
      whileTap={{ scale: 0.98 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
    >
      <Image
        src="/landing/logos/exa.png"
        alt="Exa"
        fill
        className="object-contain object-center pointer-events-none"
      />
    </motion.a>
  );
}

export default function Home() {
  return (
    <div className="min-h-screen w-full max-w-[100vw] overflow-x-clip bg-black text-white">
      {/* Nav: minimal, green CTA */}
      <nav className="fixed top-0 left-0 right-0 z-50 border-b border-zinc-800/80 bg-black/90 backdrop-blur-md">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between max-w-6xl min-w-0">
          <HackbitzLogo className="text-lg" />
          <motion.a
            href={TELEGRAM_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center rounded-lg px-4 py-2.5 text-sm font-medium bg-emerald-500 text-black hover:bg-emerald-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 focus-visible:ring-offset-2 focus-visible:ring-offset-black transition-colors"
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            transition={{ type: "spring", stiffness: 400, damping: 25 }}
          >
            Try on Telegram →
          </motion.a>
        </div>
      </nav>

      {/* Hero: headline, subline, dual CTA */}
      <section className="relative pt-32 pb-20 sm:pt-40 sm:pb-28 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_70%_50%_at_50%_-10%,rgba(16,185,129,0.12),transparent)] pointer-events-none" />
        <div className="container mx-auto px-4 relative max-w-4xl min-w-0 text-center">
          <motion.h1
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="text-4xl sm:text-5xl md:text-6xl font-bold tracking-tight text-white mb-6 leading-[1.1]"
          >
            AI agents that keep you
            <br />
            <span className="text-emerald-400">accountable for your habits</span>
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="text-lg sm:text-xl text-zinc-400 mb-10 max-w-2xl mx-auto leading-relaxed"
          >
            They know you across life, so they push you with everything in mind, keep expectations realistic, and help you win without burning you out. On Telegram.
          </motion.p>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.25 }}
            className="flex flex-wrap items-center justify-center gap-3"
          >
            <motion.a
              href={TELEGRAM_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center justify-center rounded-lg h-12 px-6 text-base font-medium bg-emerald-500 text-black hover:bg-emerald-400 transition-colors"
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              transition={{ type: "spring", stiffness: 400, damping: 25 }}
            >
              Try on Telegram →
            </motion.a>
            <motion.a
              href="#features"
              className="inline-flex items-center justify-center rounded-lg h-12 px-6 text-base font-medium border border-zinc-600 text-zinc-300 hover:border-zinc-500 hover:text-white transition-colors"
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              transition={{ type: "spring", stiffness: 400, damping: 25 }}
            >
              See how it works
            </motion.a>
          </motion.div>
        </div>
      </section>

      {/* Powered by strip */}
      <section className="py-10 border-y border-zinc-800/80">
        <div className="container mx-auto px-4 max-w-6xl min-w-0">
          <p className="text-center text-xs font-medium text-zinc-500 uppercase tracking-widest mb-8">
            Powered by
          </p>
          <div className="flex flex-wrap items-center justify-center gap-x-12 gap-y-5 min-w-0">
            <a
              href="https://modal.com"
              target="_blank"
              rel="noopener noreferrer"
              className="relative h-10 w-32 shrink-0 block opacity-70 hover:opacity-100 transition-opacity"
              aria-label="Modal"
            >
              <Image src="/landing/logos/modal.png" alt="Modal" fill className="object-contain object-center pointer-events-none" />
            </a>
            <a
              href="https://supermemory.ai"
              target="_blank"
              rel="noopener noreferrer"
              className="relative h-10 w-44 shrink-0 block opacity-70 hover:opacity-100 transition-opacity"
              aria-label="Supermemory"
            >
              <Image src="/landing/logos/supermemory.png" alt="Supermemory" fill className="object-contain object-center pointer-events-none" />
            </a>
            <ExaLogo className="opacity-70" />
          </div>
        </div>
      </section>

      {/* Problem / value prop */}
      <section className="py-20 sm:py-28">
        <div className="container mx-auto px-4 max-w-4xl min-w-0 text-center">
          <motion.h2
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-4xl sm:text-5xl md:text-6xl font-bold text-white mb-8 leading-[1.1]"
          >
            Your goals don’t stick
            <br />
            until someone’s keeping score
          </motion.h2>
          <motion.p
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-zinc-400 text-xl sm:text-2xl mb-12 max-w-2xl mx-auto leading-relaxed"
          >
            Generic trackers are one-size-fits-all. Motivation fades. <HackbitzLogo /> gives each goal a dedicated agent and shared context so you get accountability that adapts.
          </motion.p>
          <motion.a
            href={TELEGRAM_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center gap-1.5 rounded-lg h-12 px-6 text-base font-medium bg-black text-emerald-400 border border-emerald-500/30 hover:border-emerald-400/50 hover:text-emerald-300 transition-colors"
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
          >
            Try <HackbitzLogo className="[&_span]:text-emerald-400" /> on Telegram →
          </motion.a>
        </div>
      </section>

      {/* Feature pillars: 3 cards */}
      <section className="py-16 sm:py-24 bg-zinc-950/80 border-y border-zinc-800/80">
        <div className="container mx-auto px-4 max-w-5xl min-w-0">
          <motion.h2
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-2xl sm:text-4xl font-bold text-white mb-12 text-center"
          >
            Accountability that adapts to every goal
          </motion.h2>
          <motion.div
            variants={container}
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: "-40px" }}
            className="grid grid-cols-1 md:grid-cols-3 gap-6"
          >
            {[
              { title: "Agent per goal", desc: "One dedicated agent per goal. Personalized replies and nudges so you stay on track.", border: "hover:border-emerald-500/30" },
              { title: "Shared context", desc: "Agents know each other. Goals get redefined daily; focus stays clear, not overwhelming.", border: "hover:border-emerald-500/30" },
              { title: "Commands & content", desc: "/checkin, /plan, /list. Plus relevant content (articles, apps, videos) via Exa when you need it.", border: "hover:border-emerald-500/30" },
            ].map(({ title, desc, border }) => (
              <motion.div
                key={title}
                variants={item}
                className={`rounded-xl border border-zinc-800 bg-zinc-900/50 p-6 transition-colors duration-300 ${border}`}
              >
                <h3 className="text-xl font-semibold text-white mb-3">{title}</h3>
                <p className="text-base text-zinc-400 leading-relaxed">{desc}</p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* App store screenshot gallery */}
      <AppStoreGallery
        id="features"
        sectionTitle="Agent replies & accountability"
        sectionDescription="A dedicated agent per goal. Personalized replies to your logs and relevant content so you stay on track."
        items={[
          { title: "Agent per goal", description: "Each goal gets its own agent. A shared check-in summarizes what needs attention, streaks, and one clear focus.", src: "/landing/agent-per-goal.png", alt: "Leetcode and Gym agents with hackbitz check-in" },
          { title: "Replies and content", description: "Agents respond to your logs and surface relevant resources via Exa (apps, articles, videos) when you need a nudge.", src: "/landing/cuda-agent-exa.png", alt: "CUDA agent reply with Exa suggestion" },
          { title: "When you're stuck", description: "Get accountability and personalized reads when you're off track. Agents adjust tone and suggestions to help you get back on course.", src: "/landing/leetcode-burnout-exa.png", alt: "Leetcode agent on burnout with Exa links" },
        ]}
      />

      <AppStoreGallery
        className="bg-zinc-950/50"
        sectionTitle="Goals and logging"
        sectionDescription="Add goals in plain language. Set nudge and log-check schedules. Log in free text; the bot routes to the right goal or asks to create one."
        items={[
          { title: "Add a goal", description: "Natural language goal creation. Choose nudge and log-check times with inline buttons, no forms.", src: "/landing/add-goal-leetcode.png", alt: "Add goal Daily Leetcode" },
          { title: "One agent per goal", description: "Everything for that goal is tracked by a dedicated agent. Pick personality: direct or encouraging.", src: "/landing/add-goal-cuda.png", alt: "Add goal CUDA" },
          { title: "Log classification", description: "Unclear logs get a prompt: link to a goal or save as a general note. The bot learns your intent.", src: "/landing/log-classification.png", alt: "Log classification" },
        ]}
      />

      <AppStoreGallery
        sectionTitle="Commands and shared context"
        sectionDescription="/checkin for a snapshot across all goals. /plan for today's priorities. /list for active goals. Agents coordinate so focus stays clear."
        items={[
          { title: "Check-in scorecard", description: "One message: needs attention, streaks, and one clear recommendation from hackbitz across every goal.", src: "/landing/checkin-scorecard.png", alt: "Check-in scorecard" },
          { title: "Plan and list", description: "/plan and /list: today's priorities and all goals. Agents know each other so they don't overload you.", src: "/landing/plan-list.png", alt: "Plan and list commands" },
        ]}
      />

      {/* Final CTA */}
      <section className="py-24 sm:py-32 border-t border-zinc-800/80 bg-zinc-950/80">
        <div className="container mx-auto px-4 text-center max-w-2xl min-w-0">
          <motion.h2
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-2xl sm:text-3xl md:text-4xl font-bold text-white mb-4"
          >
            Get accountability that adapts
          </motion.h2>
          <motion.p
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-zinc-400 text-lg mb-10"
          >
            Try <HackbitzLogo /> on Telegram. One bot, one place: goals, logs, and agents that know each other.
          </motion.p>
          <motion.a
            href={TELEGRAM_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center rounded-lg h-12 px-8 text-base font-medium bg-emerald-500 text-black hover:bg-emerald-400 transition-colors"
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            transition={{ type: "spring", stiffness: 400, damping: 25 }}
          >
            Try on Telegram: @hackbitz_bot →
          </motion.a>
        </div>
      </section>

      {/* Footer: tagline + links */}
      <footer className="border-t border-zinc-800/80 py-12">
        <div className="container mx-auto px-4 max-w-6xl min-w-0">
          <p className="text-center text-xl font-semibold text-zinc-500 mb-8">
            Goals without accountability are just wishes.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-between gap-6">
            <HackbitzLogo className="text-sm text-zinc-500 [&_span]:text-inherit" />
            <motion.a
              href={TELEGRAM_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-zinc-400 hover:text-emerald-400 transition-colors"
            >
              @hackbitz_bot on Telegram
            </motion.a>
            <span className="text-xs text-zinc-600">Powered by Modal, Supermemory, Exa</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
