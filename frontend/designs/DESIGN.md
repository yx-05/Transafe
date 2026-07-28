---
name: Vibrant Neo-Banking
colors:
  surface: '#f8f9fa'
  surface-dim: '#d9dadb'
  surface-bright: '#f8f9fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f4f5'
  surface-container: '#edeeef'
  surface-container-high: '#e7e8e9'
  surface-container-highest: '#e1e3e4'
  on-surface: '#191c1d'
  on-surface-variant: '#424656'
  inverse-surface: '#2e3132'
  inverse-on-surface: '#f0f1f2'
  outline: '#727687'
  outline-variant: '#c2c6d8'
  surface-tint: '#0054d6'
  primary: '#0050cb'
  on-primary: '#ffffff'
  primary-container: '#0066ff'
  on-primary-container: '#f8f7ff'
  inverse-primary: '#b3c5ff'
  secondary: '#595f66'
  on-secondary: '#ffffff'
  secondary-container: '#dee3eb'
  on-secondary-container: '#5f656c'
  tertiary: '#53596b'
  on-tertiary: '#ffffff'
  tertiary-container: '#6b7284'
  on-tertiary-container: '#f8f8ff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dae1ff'
  primary-fixed-dim: '#b3c5ff'
  on-primary-fixed: '#001849'
  on-primary-fixed-variant: '#003fa4'
  secondary-fixed: '#dee3eb'
  secondary-fixed-dim: '#c2c7cf'
  on-secondary-fixed: '#161c22'
  on-secondary-fixed-variant: '#42474e'
  tertiary-fixed: '#dce2f7'
  tertiary-fixed-dim: '#c0c6db'
  on-tertiary-fixed: '#141b2b'
  on-tertiary-fixed-variant: '#404758'
  background: '#f8f9fa'
  on-background: '#191c1d'
  surface-variant: '#e1e3e4'
typography:
  display-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 40px
    fontWeight: '700'
    lineHeight: 48px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 8px
  container-padding: 24px
  gutter: 16px
  stack-sm: 12px
  stack-md: 24px
  stack-lg: 40px
---

## Brand & Style
This design system shifts away from complex security aesthetics toward a **Modern Neo-Banking** style. It prioritizes clarity, trust, and accessibility. The visual language uses high-contrast surfaces, generous white space, and soft organic shapes to create a friendly yet professional environment for financial management. 

The aesthetic is characterized by a "layered clean" approach: utilizing subtle background shifts between white and light gray to establish hierarchy without the weight of heavy borders. It evokes a feeling of efficiency and optimism, moving from a "defensive" posture to an "empowering" one.

## Colors
The palette is anchored by a **Vibrant Primary Blue (#0066FF)**, which serves as the main interactive signal. 

- **Surfaces:** Use pure white (#FFFFFF) for primary cards and content areas to maximize contrast. Use the neutral light gray (#F9FAFB) for page backgrounds to provide depth.
- **Risk Tiers:** Adapted for the light theme using a "Soft Fill / Hard Text" logic. Red, Amber, and Green should be used at 10% opacity for backgrounds with full-strength hex values for the text and icons within them.
- **Secondary Blue:** A very pale blue (#F2F7FF) is used for ghost buttons and secondary interactive regions.

## Typography
We use **Plus Jakarta Sans** for headlines and body text to provide a modern, friendly geometric feel that remains highly legible. For smaller technical data—such as account numbers, timestamps, and labels—**Inter** is utilized for its superior clarity at small scales.

Weight is used strategically to denote hierarchy; headlines are consistently bold or semi-bold, while body text remains regular weight to ensure a "breezy," uncluttered feel across data-heavy banking screens.

## Layout & Spacing
The layout follows a **Fluid Grid** system with generous safe areas. 

- **Mobile:** 4-column grid with 24px side margins and 16px gutters.
- **Desktop:** 12-column centered grid with a max-width of 1280px.
- **Rhythm:** We employ an 8px baseline grid. Internal card padding should be a minimum of 24px (3x base) to ensure the interface feels premium and uncrowded. 

Content is grouped into "Logical Buckets" using vertical stacking. The spacing between unrelated sections (e.g., Account Summary vs. Recent Transactions) should be 40px to create clear visual separation without needing dividers.

## Elevation & Depth
This design system avoids heavy shadows and instead uses **Ambient Depth**. 

- **Level 0 (Background):** #F9FAFB (Neutral Gray).
- **Level 1 (Cards/Sheet):** #FFFFFF (White) with a very soft, diffused shadow (0px 4px 20px rgba(0, 0, 0, 0.05)).
- **Level 2 (Active/Hover):** #FFFFFF with a slightly more pronounced shadow (0px 8px 30px rgba(0, 0, 0, 0.08)).

Interactions are conveyed through slight elevation lifts rather than color changes alone, giving the UI a tactile, responsive quality.

## Shapes
The shape language is defined by **High Circularity**. 

- **Primary Cards:** Use `rounded-xl` (1.5rem / 24px) to create a soft, friendly container.
- **Buttons & Inputs:** Use `rounded-lg` (1rem / 16px).
- **Status Pills:** Always use fully rounded (pill) shapes to distinguish them from interactive buttons.

This high degree of roundedness removes the "industrial" feel of traditional banking and aligns the product with modern lifestyle applications.

## Components
### Buttons
- **Primary:** Solid #0066FF background, white text, 16px roundedness. Bold typography.
- **Secondary:** Pale blue background (#F2F7FF) with blue text (#0066FF). No border.
- **Tertiary/Ghost:** No background, blue text. Use for low-emphasis actions.

### Cards
Cards are the primary organizational unit. They must always have a white background and the defined Level 1 shadow. Icons within cards should be placed inside a 48x48px rounded-square container with a light tint of the icon's color.

### Inputs
Fields should use the #F9FAFB background with a subtle 1px border (#E5E7EB). On focus, the border transitions to Primary Blue with a 2px stroke.

### Risk/Status Indicators
Risk tiers (Red/Amber/Green) should be displayed as soft-tinted chips. For example, a "High Risk" transaction uses a light red background with bold red text to ensure it is noticeable but doesn't disrupt the clean aesthetic of the light theme.