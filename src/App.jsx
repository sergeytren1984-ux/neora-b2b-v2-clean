import { useState } from "react";

https://formspree.io/f/mrbonpno
const FORMSPREE_ENDPOINT = "https://formspree.io/f/XXXXXXXX";

const t = {
  fr: {
    lang: "FR",
    switchHint: "FR → EN → RU",
    hero: "Lot d’essai pour HoReCa",
    sub: "Torréfaction de spécialité pour cafés et restaurants à Paris.",
    benefits: "Pourquoi nous ?",
    b1: "Qualité stable, profils clairs",
    b2: "Prix B2B adaptés HoReCa",
    b3: "Livraison rapide sur Paris",
    assortment: "Assortiment",
    assortmentText:
      "Espresso & filtre : Brésil, Colombie, Éthiopie, Honduras (selon récolte).",
    terms: "Conditions",
    termsList: [
      "Fixation des profils après dégustation.",
      "Volumes d’essai flexibles et calendrier de livraison discuté.",
    ],
    formTitle: "Envoyer la demande",
    f_company: "Société",
    f_person: "Contact",
    f_email: "E-mail",
    f_address: "Adresse",
    f_phone: "Téléphone",
    f_volume: "Volume mensuel estimé",
    f_comment: "Commentaire (optionnel)",
    send: "Envoyer",
    sentOk: "Merci ! Votre demande a été envoyée.",
    sentErr: "Échec d’envoi. Réessayez."
  },
  en: {
    lang: "EN",
    switchHint: "EN → RU → FR",
    hero: "Trial batch for HoReCa",
    sub: "Specialty roasting for cafés & restaurants in Paris.",
    benefits: "Why us?",
    b1: "Consistent quality, clear profiles",
    b2: "HoReCa-friendly pricing",
    b3: "Fast delivery across Paris",
    assortment: "Assortment",
    assortmentText:
      "Espresso & filter: Brazil, Colombia, Ethiopia, Honduras (by harvest).",
    terms: "Terms",
    termsList: [
      "Lock profiles after tasting feedback.",
      "Flexible pilot volumes and agreed delivery cadence.",
    ],
    formTitle: "Send request",
    f_company: "Company",
    f_person: "Contact person",
    f_email: "E-mail",
    f_address: "Address",
    f_phone: "Phone",
    f_volume: "Expected monthly volume",
    f_comment: "Comment (optional)",
    send: "Send",
    sentOk: "Thank you! Your request has been sent.",
    sentErr: "Couldn’t send. Please try again."
  },
  ru: {
    lang: "RU",
    switchHint: "RU → FR → EN",
    hero: "Пробная партия для HoReCa",
    sub: "Спешелти-обжарка для кофеен и ресторанов в Париже.",
    benefits: "Почему мы?",
    b1: "Стабильное качество, понятные профили",
    b2: "Цены под HoReCa",
    b3: "Быстрая доставка по Парижу",
    assortment: "Ассортимент",
    assortmentText:
      "Эспрессо и фильтр: Бразилия, Колумбия, Эфиопия, Гондурас (по урожаю).",
    terms: "Условия",
    termsList: [
      "Фиксируем профиль после дегустации.",
      "Гибкая пробная партия и согласованный график поставок.",
    ],
    formTitle: "Оставить заявку",
    f_company: "Компания",
    f_person: "Контактное лицо",
    f_email: "E-mail",
    f_address: "Адрес",
    f_phone: "Контактный телефон",
    f_volume: "Ожидаемый объём в месяц",
    f_comment: "Комментарий (необязательно)",
    send: "Отправить заявку",
    sentOk: "Спасибо! Ваша заявка отправлена.",
    sentErr: "Не удалось отправить. Попробуйте ещё раз."
  }
};

const order = ["ru", "fr", "en"];
const nextLang = (cur) => order[(order.indexOf(cur) + 1) % order.length];

export default function App() {
  const defaultLang = "ru"; // ← если хочешь старт с FR, поставь "fr"
  const [lang, setLang] = useState(defaultLang);
  const L = t[lang];

  const [sending, setSending] = useState(false);
  const [status, setStatus] = useState(null); // "ok" | "err" | null

  async function onSubmit(e) {
    e.preventDefault();
    setStatus(null);
    setSending(true);

    const formData = Object.fromEntries(new FormData(e.currentTarget).entries());

    // собираем полезный payload для Formspree
    const payload = {
      ...formData,
      lang,
      _subject: `NEORA B2B — заявка (${lang.toUpperCase()}) — ${formData["company"] || formData["Компания"] || ""}`,
    };

    try {
      const r = await fetch(FORMSPREE_ENDPOINT, {
        method: "POST",
        headers: { "Accept": "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error("bad status");
      setStatus("ok");
      e.currentTarget.reset();
    } catch {
      setStatus("err");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="min-h-screen bg-white text-neutral-900">
      {/* HEADER */}
      <header className="sticky top-0 z-50 backdrop-blur bg-white/80 border-b">
        <div className="max-w-5xl mx-auto px-5 py-3 flex items-center justify-between">
          {/* логотип: только слово NÉORA (в svg), без кружка */}
          <img src="/logo.svg" alt="NÉORA" className="h-10 w-auto" />
          <button
            onClick={() => setLang(nextLang(lang))}
            className="text-xs md:text-sm border px-3 py-1.5 rounded-lg bg-white hover:bg-neutral-50"
            title={L.switchHint}
          >
            {L.lang}
          </button>
        </div>
      </header>

      {/* HERO */}
      <section className="max-w-5xl mx-auto grid md:grid-cols-2 gap-7 px-5 pt-10">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{L.hero}</h1>
          <p className="mt-2 text-neutral-600">{L.sub}</p>

          {/* ФОРМА — Formspree (AJAX) */}
          <form onSubmit={onSubmit} className="mt-6 grid md:grid-cols-2 gap-4 max-w-3xl">
            {/* имя полей на английском — удобно для email-писем; плейсхолдеры — локализованные */}
            <input
              required name="company"
              placeholder={L.f_company}
              className="border rounded-lg px-3 py-2"
            />
            <input
              required name="person"
              placeholder={L.f_person}
              className="border rounded-lg px-3 py-2"
            />
            <input
              required type="email" name="email"
              placeholder={L.f_email}
              className="border rounded-lg px-3 py-2"
            />
            <input
              required name="phone"
              placeholder={L.f_phone}
              className="border rounded-lg px-3 py-2"
            />
            <input
              required name="address"
              placeholder={L.f_address}
              className="border rounded-lg px-3 py-2 md:col-span-2"
            />
            <input
              required name="volume"
              placeholder={L.f_volume}
              className="border rounded-lg px-3 py-2 md:col-span-2"
            />
            <textarea
              name="comment"
              placeholder={L.f_comment}
              className="border rounded-lg px-3 py-2 min-h-[110px] md:col-span-2"
            />
            <button
              type="submit"
              disabled={sending}
              className="bg-[var(--brand)] text-white font-semibold rounded-lg px-4 py-2 md:col-span-2 hover:opacity-90 transition disabled:opacity-60"
            >
              {sending ? "…" : L.send}
            </button>

            {status === "ok"  && <p className="text-green-600 md:col-span-2">{L.sentOk}</p>}
            {status === "err" && <p className="text-red-600 md:col-span-2">{L.sentErr}</p>}
          </form>
        </div>

        {/* справа — просто placeholder-карточка, НЕ «контакты» */}
        <div className="border rounded-2xl p-4">
          <div className="aspect-[4/3] w-full rounded-xl border grid place-items-center text-sm text-neutral-500">
            Image / pack mock (optional)
          </div>
        </div>
      </section>

      {/* BENEFITS */}
      <section className="max-w-5xl mx-auto px-5 pt-6">
        <h2 className="text-lg font-semibold">{L.benefits}</h2>
        <div className="grid md:grid-cols-3 gap-4 mt-3">
          <Card>{L.b1}</Card>
          <Card>{L.b2}</Card>
          <Card>{L.b3}</Card>
        </div>
      </section>

      {/* ASSORTMENT */}
      <section className="max-w-5xl mx-auto px-5 pt-6">
        <h2 className="text-lg font-semibold">{L.assortment}</h2>
        <p className="text-neutral-700 mt-2">{L.assortmentText}</p>
      </section>

      {/* TERMS — без «помесячной платы» */}
      <section className="max-w-5xl mx-auto px-5 pt-6 pb-10">
        <h2 className="text-lg font-semibold">{L.terms}</h2>
        <ul className="list-disc pl-5 mt-2 space-y-1">
          {L.termsList.map((x, i) => <li key={i}>{x}</li>)}
        </ul>
      </section>

      {/* НИЗ СТРАНИЦЫ: без «контактов» — только аккуратный футер */}
      <footer className="border-t text-center text-sm text-neutral-600 py-4">
        © 2025 NÉORA — Paris · neora-b2b.app
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
