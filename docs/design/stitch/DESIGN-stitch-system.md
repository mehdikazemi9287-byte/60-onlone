---
name: Shast Online Enterprise Commerce
colors:
  surface: '#f8f9ff'
  surface-dim: '#d0dbeb'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eef4ff'
  surface-container: '#e4efff'
  surface-container-high: '#dee9fa'
  surface-container-highest: '#d8e3f4'
  on-surface: '#111c28'
  on-surface-variant: '#424752'
  inverse-surface: '#27313e'
  inverse-on-surface: '#e9f1ff'
  outline: '#737783'
  outline-variant: '#c2c6d3'
  surface-tint: '#215db1'
  primary: '#003878'
  on-primary: '#ffffff'
  primary-container: '#034ea2'
  on-primary-container: '#a6c3ff'
  inverse-primary: '#acc7ff'
  secondary: '#47607c'
  on-secondary: '#ffffff'
  secondary-container: '#c2dcfd'
  on-secondary-container: '#48617d'
  tertiary: '#612a00'
  on-tertiary: '#ffffff'
  tertiary-container: '#843c00'
  on-tertiary-container: '#ffb284'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d7e2ff'
  primary-fixed-dim: '#acc7ff'
  on-primary-fixed: '#001a40'
  on-primary-fixed-variant: '#004591'
  secondary-fixed: '#d0e4ff'
  secondary-fixed-dim: '#afc9e9'
  on-secondary-fixed: '#001d34'
  on-secondary-fixed-variant: '#2f4963'
  tertiary-fixed: '#ffdbc8'
  tertiary-fixed-dim: '#ffb68b'
  on-tertiary-fixed: '#321200'
  on-tertiary-fixed-variant: '#753400'
  background: '#f8f9ff'
  on-background: '#111c28'
  surface-variant: '#d8e3f4'
typography:
  headline-xl:
    fontFamily: Plus Jakarta Sans
    fontSize: 36px
    fontWeight: '800'
    lineHeight: 44px
    letterSpacing: -0.02em
  headline-xl-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 28px
    fontWeight: '800'
    lineHeight: 36px
    letterSpacing: -0.01em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 36px
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 22px
    fontWeight: '700'
    lineHeight: 30px
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '700'
    lineHeight: 28px
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '700'
    lineHeight: 24px
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 26px
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
  body-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  label-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
  label-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
  label-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 10px
    fontWeight: '700'
    lineHeight: 14px
    letterSpacing: 0.02em
  price-display:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '800'
    lineHeight: 24px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-tablet: 1.5rem
  margin-desktop: 2.5rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

This design system models the functional, high-trust digital commerce platform of 60online (شصت‌آنلاین). The visual identity balances institutional reliability with agile B2B and B2C procurement efficiency, specialized for bulk purchase workflows, custom pack configuration, and direct corporate orders.

### Visual Aesthetic & Philosophy
The aesthetic fuses **Corporate / Modern** precision with soft **Tonal Layering**:
- **Trustworthy & Structured:** Strict reliance on mathematical grids, crisp micro-borders, and high legibility across Persian and Latin typography.
- **Calm Warmth & Focus:** Soft pastel hero containers (mint green `#EDF3EE`) establish welcoming contextual zones, while sharp white cards ensure fast visual parsing of product specs, pack quantities, and tiers.
- **Action Hierarchy:** High-contrast navy (`#112D46`) drives transaction anchors, brand blue (`#034EA2`) establishes system identity, and energetic orange (`#FF7A00`) spotlights institutional savings and wholesale price markers.

### Target Audience & Tone
Engineered for corporate procurement officers, organizational gift planners, and individual consumers seeking verified commercial goods. The interface evokes competence, absolute price transparency, and seamless navigation.

## Colors

The color system delivers high contrast, unambiguous affordance, and clear functional tiers across inventory screens, pack builders, and checkout steps.

### Palette Architecture
- **Primary Brand (`#034EA2`):** Primary branding, verified credentials, active navigation indicators, and linked metadata.
- **Secondary Action / CTA (`#112D46`):** Deep navy reserved for definitive commercial decisions: "Add to Pack", "Finalize Order", and primary checkout buttons.
- **Tertiary Accent / Badge (`#FF7A00` & `#E65100`):** Expressive warm orange used exclusively for volume discount markers, wholesale badges, promotional countdowns, and commercial alerts.
- **Canvas & Surface Neutral (`#F9F9F9`):** Foundation page background providing low eye-strain for data-intensive sessions.
- **Surface Elevation (`#FFFFFF`):** High-clarity foreground panels, cards, and modal canvases.
- **Contextual Tint (`#EDF3EE`):** Soft mint green reserved for hero sections, pack assembly stages, and highlight banners.
- **Hairline Dividers (`#E5E7EB`):** Crisp structural borders defining cards, table rows, and segment dividers without visual noise.

## Typography

The design system is calibrated for bidirectional text support, pairing clean contemporary Latin typography (`Plus Jakarta Sans`) with native RTL implementations utilizing `Vazirmatn` in Persian localized builds.

### Typographic Principles
- **Font Stack Hierarchy:** The fallback sequence adheres to `Vazirmatn, "Plus Jakarta Sans", system-ui, -apple-system, sans-serif` to guarantee native rendering across Persian numeral sets and Latin alphanumeric SKU codes.
- **RTL Baseline Alignment:** Persian line-heights are expanded by roughly 10-15% compared to standard Latin baselines to preserve dot accents and diacritics in dense technical tables.
- **Numeric Clarity:** Price tags, quantities, and bulk volume discount tables utilize tabular figure alignments (`tnum`) to maintain vertical parity in financial summaries.

## Layout & Spacing

The layout philosophy utilizes a responsive 12-column grid system with strict rhythmic boundaries, engineered for both mobile catalog scanning and multi-column desktop pack-builder workstations.

### Grid Breakpoints & Alignment
- **Desktop (≥ 1280px):** 12 columns, max-width `1280px` centered canvas, `gutter-desktop: 1.5rem`, `margin-desktop: 2.5rem`.
- **Tablet (768px – 1279px):** 8 columns, fluid canvas, `gutter: 1rem`, `margin-tablet: 1.5rem`.
- **Mobile (< 768px):** 4 columns, fluid canvas, `gutter: 1rem`, `margin: 1rem`.

### Spatial Flow
Component paddings and item separations are constrained strictly to the `space-*` scale. Sectional vertical cadence uses `space-xl` for content separation, while intra-component clustering (e.g., input icons, badge text offsets) remains pinned to `space-xs` and `space-sm`.

## Elevation & Depth

Visual hierarchy is maintained through crisp surface planes and tonal contrasts rather than aggressive, muddy drop shadows.

### Surface Strategy
- **Layer 0 (Canvas):** Base background `#F9F9F9`.
- **Layer 1 (Card & Section):** Crisp white `#FFFFFF` surface enclosed by a `#E5E7EB` 1px hairline border.
- **Layer 2 (Ambient Float):** Interactive elements on hover and active filter dropdowns adopt a faint, diffused shadow: `0 4px 16px -2px rgba(17, 45, 70, 0.06)`.
- **Layer 3 (Overlay / Modal / Drawer):** Cart drawers, quick-view sheets, and corporate quotation modals use `0 12px 32px -4px rgba(17, 45, 70, 0.12)`, supported by a `rgba(17, 45, 70, 0.4)` backdrop veil with subtle `backdrop-filter: blur(4px)`.
- **Layer 4 (Tonal Highlight Surfaces):** Non-elevated contextual zones (such as category wrappers and pack summary hero strips) leverage solid `#EDF3EE` fills with 0px shadow.

## Shapes

The design system applies a uniform corner radius philosophy centered on `roundedness: 2` (base `0.5rem` / `8px`), expanding to `12px` (`0.75rem`) for standard cards and containers to reflect the friendly, clean pack aesthetic.

### Radius Application Tokens
- **Micro Elements (Checkboxes, Steppers, Small Badges):** `4px` (`rounded-sm`).
- **Form Controls & Action Buttons:** `8px` (`rounded-md`).
- **Product Cards, Modals & Hero Banners:** `12px` (`rounded-lg`).
- **Pill Badges & Tag Filters:** Full circular curvature (`rounded-full` / 9999px) to contrast against rectangular grid modules.

## Components

### Buttons
- **Primary Transactional (Navy):** Solid `#112D46` background, white label, `8px` corner radius, `space-md` horizontal padding. On hover, subtle luminance drop to `#0B1F31`.
- **Secondary Brand (Blue):** Solid `#034EA2` background, white label, used for navigational triggers, pack configuration steps, and secondary CTAs.
- **Outline / Ghost:** Transparent background, `1px` solid `#E5E7EB` border, text `#112D46`. On hover, background shifts to `#F9F9F9`.

### Chips & Price Badges
- **Corporate Discount Badge:** Solid `#FF7A00` or `#E65100` background with crisp white typography (`label-sm`), pill-shaped radius (`9999px`), inline padding `6px 10px`.
- **Category Filter Chips:** White `#FFFFFF` base, `1px` border `#E5E7EB`, text `#5A6573`. Active state switches to `#EDF3EE` fill, border `#034EA2`, text `#034EA2`.

### Product & Pack Cards
- **Construction:** Pure white `#FFFFFF` background, `12px` corner radius, `1px` uniform perimeter border `#E5E7EB`.
- **Padding & Structure:** Internal padding of `space-md`. Top media container with subtle neutral tint `#F9F9F9` for asset framing; lower data stack displaying title, stock indicators, and tabular price lockups.
- **Hover Micro-interaction:** Transition border-color to `#034EA2` and elevate with faint ambient float shadow.

### Inputs & Quantity Steppers
- **Text Inputs:** White background, `8px` border radius, `1px` border `#E5E7EB`, placeholder `#9CA3AF`. Active focus ring: `2px` solid `#034EA2` with `0px` shadow offset.
- **Quantity Pack Steppers:** Segmented container with minus, input field, and plus actions grouped in a single `8px` frame bordered by `#E5E7EB`, with high-contrast `#112D46` icons.

### Lists & Tables
- **Data Rows:** Alternate or clean `#FFFFFF` rows divided by `#E5E7EB` horizontal borders. Right-aligned RTL Persian typography, left-aligned currency figures (`Rials` or `Tomans`) with bold weight.