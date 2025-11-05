import { useState } from "react"

const t = {
  fr: {
    lang: "FR", switchTo: "EN", switchTo2: "RU",
    hero: "Lot d’essai pour HoReCa",
    sub: "Torréfaction de spécialité pour cafés et restaurants à Paris.",
    cta: "Envoyer la demande",
    benefits: "Pourquoi nous ?",
    b1: "Qualité stable, profils clairs",
    b2: "Prix B2B transparents",
    b3: "Livraison rapide sur Paris",
    assortment: "Assortiment",
    assortmentText: "Espresso & filtre : Brésil, Colombie, Éthiopie, Honduras (selon récolte). Profil HoReCa.",
    terms: "Conditions",
    termsList: [
      "Volumes d’essai flexibles (lot pilote HoReCa).",
      "Contrats B2B simples, facturation mensuelle.",
      "Livraison sur Paris intra-muros sous 24–72 h."
    ],
    contact: "Contact",
    success: "Merci, votre demande a été reçue !",
    footer: "© 2025 NEORA — Paris · neora-b2b.app"
  },
  en: {
    lang: "EN", switchTo: "FR", switchTo2: "RU",
    hero: "Trial batch for HoReCa",
    sub: "Specialty roasting for cafés & restaurants in Paris.",
    cta: "Send request",
    benefits: "Why us?",
    b1: "Consistent quality & clear profiles",
    b2: "Transparent B2B pricing",
    b3: "Fast delivery in Paris",
    assortment: "Assortment",
    assortmentText: "Espresso & filter: Brazil, Colombia, Ethiopia, Honduras (by harvest). HoReCa-tuned.",
    terms: "Terms",
    termsList: [
      "Flexible pilot volumes (HoReCa trial).",
      "Simple B2B contracts, monthly invoicing.",
      "Paris delivery within 24–72 h."
    ],
    contact: "Contact",
    success: "Thank you, your request has been received!",
    footer: "© 2025 NEORA — Paris · neora-b2b.app"
  },
  ru: {
    lang: "RU", switchTo: "FR", switchTo2: "EN",
    hero: "Пробная партия для HoReCa",
    sub: "Спешиалти-обжарка для кафе и ресторанов в Париже.",
    cta: "Отправить заявку",
    benefits: "Почему мы?",
    b1: "Стабильное качество, понятные профили",
    b2: "Прозрачные B2B-цены",
    b3: "Быстрая доставка по Парижу",
    assortment: "Ассортимент",
    assortmentText: "Эспрессо и фильтр: Бразилия, Колумбия, Эфиопия, Гондурас (по урожаю). Настроено под HoReCa.",
    terms: "Условия",
    termsList: [
      "Гибкие пробные объёмы (пилотная партия HoReCa).",
      "Простые B2B-договора, помесячная оплата.",
      "Доставка по Парижу 24–72 ч."
    ],
    contact: "Контакты",
    success: "Спасибо, ваша заявка принята!",
    footer: "© 2025 NEORA — Paris · neora-b2b.app"
  }
}

export default function App() {
  const [lang, setLang] = useState("fr")
  const [ok, setOk] = useState(false)
  const L = t[lang]

  const cycle = () => {
    setLang(prev => prev === 'fr' ? 'en' : prev === 'en' ? 'ru' : 'fr')
    setOk(false)
  }

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="sticky top-0 z-50 backdrop-blur bg-white/80 border-b">
        <div className="max-w-5xl mx-auto px-5 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Основной логотип */}
            <img src="/logo.svg" alt="NEORA" className="h-10 w-auto" />
            {/* Круглый логотип уменьшен */}
            <img src="/logo-round.svg" alt="NEORA emblem" className="h-6 w-auto opacity-80" />
          </div>

          <button
            onClick={cycle}
            className="text-sm border px-3 py-2 rounded-lg bg-white"
            title={`${L.switchTo} / ${L.switchTo2}`}
          >
            {L.lang}
          </button>
        </div>
      </header>

      {/* Hero */}
      <section className="max-w-5xl mx-auto grid md:grid-cols-2 gap-7 px-5 pt-10">
        <div>
          {/* Заголовок меньше логотипа по восприятию */}
          <h1 className="text-2xl font-bold tracking-tight">{L.hero}</h1>
          <p className="mt-2 text-neutral-600">{L.sub}</p>

          <form
            onSubmit={(e)=>{e.preventDefault(); setOk(true); e.currentTarget.reset()}}
            className="mt-5 flex flex-col gap-3 max-w-md"
          >
            <input required name="name" placeholder="Name / Имя" className="border rounded-lg px-3 py-2"/>
            <input required type="email" name="email" placeholder="E-mail" className="border rounded-lg px-3 py-2"/>
            <textarea name="msg" placeholder="Message" className="border rounded-lg px-3 py-2 min-h-[90px]"></textarea>
            <button className="bg-[var(--brand)] text-white font-semibold rounded-lg px-4 py-2">{L.cta}</button>
            {ok && <p className="text-green-600 font-medium">{L.success}</p>}
          </form>
        </div>

        {/* Визуальный блок (не «Условия») */}
        <div className="border rounded-2xl p-4">
          <div className="aspect-[4/3] w-full rounded-xl border grid place-items-center text-sm text-neutral-500">
            Image / pack mock (optional)
          </div>
        </div>
      </section>

      {/* Benefits */}
      <section className="max-w-5xl mx-auto px-5 pt-6">
        <h2 className="text-lg font-semibold">{L.benefits}</h2>
        <div className="grid md:grid-cols-3 gap-4 mt-3">
          <Card>{L.b1}</Card>
          <Card>{L.b2}</Card>
          <Card>{L.b3}</Card>
        </div>
      </section>

      {/* Assortment */}
      <section className="max-w-5xl mx-auto px-5 pt-6">
        <h2 className="text-lg font-semibold">{L.assortment}</h2>
        <p className="text-neutral-700 mt-2">{L.assortmentText}</p>
      </section>

      {/* Условия — одноколоночный блок (правый убран) */}
      <section className="max-w-5xl mx-auto px-5 pt-6">
        <h2 className="text-lg font-semibold">{L.terms}</h2>
        <ul className="list-disc pl-5 mt-2 space-y-1">
          {L.termsList.map((x,i)=><li key={i}>{x}</li>)}
        </ul>
      </section>

      {/* Contact */}
      <section className="max-w-5xl mx-auto px-5 py-10">
        <h2 className="text-lg font-semibold">{L.contact}</h2>
        <div className="mt-3 flex gap-3">
          <a className="border rounded-lg px-4 py-2 font-semibold" href="mailto:hello@neora.coffee">hello@neora.coffee</a>
          <a className="border rounded-lg px-4 py-2 font-semibold" href="https://wa.me/33600000000">WhatsApp</a>
        </div>
      </section>

      <footer className="border-t text-center text-sm text-neutral-600 py-4">
        {L.footer}
      </footer>
    </div>
  )
}

function Card({children}) {
  return (
    <div className="border rounded-2xl p-4 shadow-sm bg-white font-medium">
      {children}
    </div>
  )
}
