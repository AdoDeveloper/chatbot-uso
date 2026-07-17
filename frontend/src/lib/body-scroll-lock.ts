// Contador de referencias compartido entre Dialog y Sheet: al cerrar uno de
// varios overlays abiertos simultáneamente, el scroll del body solo debe
// restaurarse cuando el último overlay se cierra, no con cualquier cleanup.
let lockCount = 0

export function lockBodyScroll() {
  if (lockCount === 0) document.body.style.overflow = "hidden"
  lockCount += 1
}

export function unlockBodyScroll() {
  lockCount = Math.max(0, lockCount - 1)
  if (lockCount === 0) document.body.style.overflow = ""
}
