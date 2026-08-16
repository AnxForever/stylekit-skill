# Popular Style Signatures

Visual traits, forbidden classes, and required classes for the most-requested StyleKit styles. For any style, always fetch the live spec — this table is a quick orientation aid, not a replacement for the API.

| Style | Key Visual Traits | Forbidden | Required |
|-------|------------------|-----------|----------|
| `neo-brutalist` | Black borders, hard shadows, no rounding | `rounded-*`, `shadow-lg`, gradients | `rounded-none`, `border-black`, hard-edge `shadow-[...]` |
| `glassmorphism` | Frosted glass, blur, translucent | `rounded-none`, `bg-white`, `border-black` | `backdrop-blur-*`, `bg-white/N`, `border-white/N` |
| `neumorphism` | Soft extruded surfaces, subtle shadows | Hard shadows, high contrast borders | Dual shadows (light + dark), soft bg |
| `claymorphism` | Puffy 3D clay look, inner shadows | Flat shadows, sharp corners | Inner shadow, rounded corners, pastel bg |
| `apple-style` | Clean, precise, SF Pro feel | Heavy borders, loud colors | Subtle shadows, system fonts, generous whitespace |
| `material-design` | Elevation system, ripple effects | Hard-edge shadows, no-radius | `shadow-md`, `rounded-lg`, elevation layers |
| `pixel-art` | Pixelated edges, 8-bit aesthetic | Smooth gradients, anti-aliased borders | `rounded-none`, pixel fonts, step-based colors |
| `cyberpunk-neon` | Neon glows, dark bg, electric colors | Pastel colors, soft shadows | Neon `shadow-[0_0_Npx_color]`, dark bg, bright accents |
| `swiss-style` | Grid-based, Helvetica, minimal | Decorative elements, rounded corners | Grid alignment, sans-serif, high contrast |
| `art-deco` | Gold accents, geometric patterns, luxury | Casual fonts, muted colors | Gold/brass tones, geometric borders, serif fonts |
| `ghibli-style` | Warm watercolor, hand-drawn feel | Sharp edges, neon colors | Soft pastels, rounded shapes, warm tones |
| `vaporwave` | Purple/pink gradients, retro-futurism | Muted earth tones, minimal palette | Gradient bg, neon pink/cyan, retro fonts |
| `dark-mode` | Dark surfaces, subtle elevation | Pure white bg, low contrast | Dark bg, muted text, subtle borders |
| `editorial` | Typography-driven, magazine layout | Heavy UI chrome, small text | Large type, generous spacing, serif headings |
| `korean-minimal` | Soft, airy, pastel, generous whitespace | Heavy borders, loud colors | Subtle pastels, thin borders, rounded-2xl |

## Style axes

- **Brand-inspired**: Apple, Stripe, Linear, Notion, GitHub
- **Aesthetic**: Glassmorphism, Neo-Brutalist, Cyberpunk, Vaporwave
- **Cultural**: Bauhaus, Ghibli, Wabi-Sabi, Ukiyo-e

## Browsing the catalog

- All styles: https://www.stylekit.top/styles
- JSON list: `GET https://www.stylekit.top/api/styles`
- By collection (dark-mode, retro-vintage, anime-manga, game-ui, colorful-bold, hand-drawn): https://www.stylekit.top/collections
