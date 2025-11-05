import { useState } from "react";

/** Formspree endpoint — заявки придут на твою почту */
const FORMSPREE_ENDPOINT = "https://formspree.io/f/mrbonpno";

const t = {
  fr: {
    lang: "FR", switchTo: "EN",
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
    form: {
      title: "Laissez votre demande",
      company: "Société",
      contact: "Personne de contact",
      email: "E-mail",
      address: "Adresse",
      phone: "Téléphone",
      volume: "Volume mensuel attendu (kg)",
      comment: "Commentaire",
      submit: "Envoyer la demande",
      ok: "Merci ! Votre demande a été envoyée."
    },
    footer: "© 2025 NÉORA — Paris · neora-b2b.app"
  },
  en: {
    lang: "EN", switchTo: "FR",
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
    form: {
      title: "Leave a request",
      company: "Company",
      contact: "Contact person",
      email: "E-mail",
      address: "Address",
      phone: "Phone",
      volume: "Expected monthly volume (kg)",
      comment: "Comment",
      submit: "Send request",
      ok: "Thanks! Your request has been sent."
    },
    footer: "© 2025 NÉORA — Paris · neora-b2b.app"
  },
  ru: {
    lang: "RU", switchTo: "FR",
    hero: "Пробная партия для HoReCa",
    sub: "Спешиалти-обжарка для кофеен и ресторанов в Париже.",
    cta: "Отправить заявку",
    benefits: "Почему мы?",
    b1: "Стабильное качество, ясные профили",
    b2: "Прозрачные B2B-цены",
    b3: "Быстрая доставка по Парижу",
    assortment: "Ассортимент",
    assortmentText: "Эспрессо и фильтр: Бразилия, Колумбия, Эфиопия, Гондурас (по урожаю). Профиль HoReCa.",
    terms: "Условия",
    termsList: [
      "Гибкие тестовые объёмы (пилот для HoReCa).",
      "Простые B2B-договоры, помесячная отчётность.",
      "Доставка по Парижу 24–72 ч."
    ],
    form: {
      title: "Оставить заявку",
      company: "Компания",
      contact: "Контактное лицо",
      email: "E-mail",
      address: "Адрес",
      phone: "Телефон",
      volume: "Ожидаемый объём в месяц (кг)",
      comment: "Комментарий",
      submit: "Отправить заявку",
      ok: "Спасибо! Ваша заявка отправлена."
    },
    footer: "© 2025 NÉORA — Paris · neora-b2b.app"
  }
};

export default function App() {
  const [lang, setLang] = useState<"fr" | "en" | "ru">("fr");
  const [ok, setOk] = useState(false);
  const L = t[lang];

  async function onSubmit(e) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());

    const resp = await fetch(FORMSPREE_ENDPOINT, {
      method: "POST",
      headers: { "Accept": "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });

    if (resp.ok) {
      setOk(true);
      form.reset();
      setTimeout(() => setOk(false), 5000);
    } else {
      alert("Submit error. Try again or email hello@neora.coffee");
    }
  }

  return (
    <div className="min-h-screen">
      {/* Header — логотип одним словом, без кружка */}
      <header className="sticky top-0 z-50 backdrop-blur bg-white/80 border-b">
        <div className="max-w-5xl mx-auto px-5 py-3 flex items-center justify-between">
          <div className="text-2xl font-bold tracking-tight">
            <span style={{ letterSpacing: "0.5px" }}>
              N<span style={{ color: "var(--brand, #C58A44)" }}>É</span>ORA
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setLang(lang === "fr" ? "en" : lang === "en" ? "ru" : "fr")}
              className="text-sm border px-3 py-2 rounded-lg bg-white"
              title={L.switchTo}
            >
              {L.lang}
            </button>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="max-w-5xl mx-auto grid md:grid-cols-2 gap-7 px-5 pt-10">
        {/* Форма заявки */}
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{L.hero}</h1>
          <p className="mt-2 text-neutral-600">{L.sub}</p>

          <form onSubmit={onSubmit} className="mt-5 flex flex-col gap-3 max-w-md">
            <input name="company" required placeholder={L.form.company} className="border rounded-lg px-3 py-2" />
            <input name="contact" required placeholder={L.form.contact} className="border rounded-lg px-3 py-2" />
            <input type="email" name="email" required placeholder={L.form.email} className="border rounded-lg px-3 py-2" />
            <input name="address" placeholder={L.form.address} className="border rounded-lg px-3 py-2" />
            <input name="phone" placeholder={L.form.phone} className="border rounded-lg px-3 py-2" />
            <input name="monthlyVolume" placeholder={L.form.volume} className="border rounded-lg px-3 py-2" />
            <textarea name="comment" placeholder={L.form.comment} className="border rounded-lg px-3 py-2 min-h-[90px]" />

            <button className="bg-[var(--brand,#C58A44)] text-white font-semibold rounded-lg px-4 py-2">
              {L.form.submit}
            </button>

            {ok && <p className="text-green-600 font-medium">{L.form.ok}</p>}
          </form>
        </div>

        {/* Правый блок (мок изображения) */}
        <div className="border rounded-2xl p-4">
          <div className="aspect-[4/3] w-full rounded-xl border grid place-items-center text-sm text-neutral-500">
            Image / pack mock (optional)
          </div>
        </div>
      </section>

      {/* Почему мы */}
      <section className="max-w-5xl mx-auto px-5 pt-6">
        <h2 className="text-lg font-semibold">{L.benefits}</h2>
        <div className="grid md:grid-cols-3 gap-4 mt-3">
          <Card>{L.b1}</Card>
          <Card>{L.b2}</Card>
          <Card>{L.b3}</Card>
        </div>
      </section>

      {/* Ассортимент */}
      <section className="max-w-5xl mx-auto px-5 pt-6">
        <h2 className="text-lg font-semibold">{L.assortment}</h2>
        <p className="text-neutral-700 mt-2">{L.assortmentText}</p>
      </section>

      {/* Условия */}
      <section className="max-w-5xl mx-auto px-5 pt-6 pb-12">
        <h2 className="text-lg font-semibold">{L.terms}</h2>
        <ul className="list-disc pl-5 mt-2 space-y-1">
          {L.termsList.map((x, i) => <li key={i}>{x}</li>)}
        </ul>
      </section>

      {/* Контакты/подвал — убрали «контакты» блок, только сдержанный футер */}
      <footer className="border-t text-center text-sm text-neutral-600 py-4">
        {L.footer}
      </footer>
    </div>
  );
}

function Card({ children }) {
  return (
    <div className="border rounded-2xl p-4 shadow-sm bg-white font-medium">
      {children}
    </div>
  );
}
