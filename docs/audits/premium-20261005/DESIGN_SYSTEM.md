# Commerce foundations

Implementation: `frontend/src/app/premium.css` and shared `ProductMedia.tsx`.

| Role | Rule |
| --- | --- |
| Typography | Vazirmatn existing font; 13px supporting, 15px body, fluid 24–36px section/PDP title, 32–56px display; Persian line height 1.8–2 |
| Spacing | 4 / 8 / 12 / 16 / 24 / 32 / 48 / 72px tokens; mobile sections 48px, desktop 72px |
| Container/grid | Existing 1280px maximum; existing Tailwind 640 / 768 / 1024px breakpoints; cards wrap rather than force price truncation |
| Surfaces | Warm paper #faf9f6, white content, muted media #f4f5f2; navy #0a2735 and blue #004e72 identity |
| Radius/elevation | 10px controls, 16px cards, 24px composed panels; no resting heavy shadows, restrained desktop hover shadow |
| Buttons/inputs | Blue/navy primary, outlined secondary; 44px card controls and 48px form/action controls; visible keyboard outlines |
| Product media | Square contain with consistent padding; original ratio preserved; PDP priority high, card images lazy; width/height reserve geometry |
| Empty/errors | Textual, accessible missing image; quote state from null price; explicit API error distinct from empty result |
| Motion | 160/240ms easing token; image zoom only with fine pointer/hover; reduced motion suppresses animations/transforms and smooth scrolling |
| RTL | Logical spacing/insets, real Persian copy, wrapping titles and prices; no dependency on hover for actions |

Verified local originals use installed Next/Sharp responsive srcset and WebP negotiation at quality 85; cached derivatives do not replace originals. Future external images retain native presentation. No fabricated price, stock, discount, review count, eligibility or product view. Existing color/utility foundations remain available to operational pages; this layer refines their shared surfaces without changing their workflows.
