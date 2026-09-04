"use client"

import { createContext, useContext, useEffect, useSyncExternalStore } from "react"

export type PortalLocale = "vi" | "en"
type TranslationValues = Record<string, string | number>

const vi = {
  languageLabel: "Ngôn ngữ",
  brandTagline: "King Bug Castle · vương quốc riêng",
  online: "trực tuyến",
  playerLedger: "Sổ người chơi",
  patronDesk: "Bàn ủng hộ",
  backLedger: "Về sổ người chơi",
  loadingLedger: "Đang mở sổ người chơi…",
  loadingDonate: "Đang mở quầy ủng hộ…",
  playerAccess: "Quyền truy cập người chơi",
  welcomeLead: "Trở lại",
  welcomeEmphasis: "vương quốc của bạn.",
  welcomeCopy: "Mở đúng save game, đổi vé thành phần thưởng và nhận thư thẳng trong game.",
  googleRequirement: "Tài khoản Google phải từng đăng nhập vào game.",
  continueGoogle: "Tiếp tục với Google",
  guestAccess: "Truy cập Guest",
  guestTitle: "Vào bằng mã được cấp",
  guestCopy: "Quản trị viên cấp tên đăng nhập và mật khẩu tạm sau khi xác nhận tài khoản game của bạn.",
  username: "Tên đăng nhập",
  password: "Mật khẩu",
  openingLedger: "Đang mở sổ…",
  signIn: "Đăng nhập",
  tempPasswordPrompt: "Hãy đổi mật khẩu tạm thời của bạn.",
  loginFailed: "Không thể đăng nhập.",
  passwordChanged: "Đã đổi mật khẩu. Hãy đăng nhập lại.",
  passwordChangeFailed: "Không thể đổi mật khẩu.",
  rewardSent: "Đã dùng 1 vé và gửi {reward} vào hòm thư trong game.",
  lastRewardSent: "Đã gửi {reward} vào hòm thư trong game. Bạn đã hết vé.",
  redeemFailed: "Không thể đổi vé.",
  requestSubmitted: "Yêu cầu đã được gửi. 1 vé đã được giữ cho yêu cầu này.",
  requestFailed: "Không thể gửi yêu cầu.",
  donationSubmitted: "Đã gửi ghi chú ủng hộ. Quản trị viên sẽ kiểm tra thủ công.",
  donationPageSubmitted: "Đã gửi ghi chú. Quản trị viên sẽ kiểm tra và quyết định quà tặng thủ công.",
  donationFailed: "Không thể gửi ghi chú.",
  linkedPlayerAria: "Thông tin người chơi",
  linkedPlayer: "Người chơi đã liên kết",
  signOut: "Thoát",
  ticketReserve: "Kho vé",
  ticketTitle: "Vé của bạn",
  ticketCopy: "Tính năng nhận vé qua video đang tạm khóa để bảo vệ số dư của người chơi.",
  ticketLoading: "Đang tải ví…",
  ticketUnit: "vé",
  today: "Hôm nay",
  refresh: "Làm mới",
  ticketRefreshFailed: "Không thể cập nhật số vé.",
  cooldown: "Lượt tiếp theo mở sau {minutes} phút.",
  videoDisabled: "Video nhận vé đang tạm khóa",
  claimEyebrow: "Nhận qua hòm thư",
  claimTitle: "Đổi vé, nhận thư",
  claimCopy: "Mỗi lần đổi dùng một vé. Phần thưởng sẽ chờ trong hòm thư game của bạn.",
  reward: "Phần thưởng",
  useTicket: "Dùng 1 vé",
  confirmReward: "Gửi {reward} đến hòm thư game?",
  sending: "Đang gửi…",
  confirm: "Xác nhận",
  cancel: "Hủy",
  catalogLoading: "Đang đọc danh sách phần thưởng…",
  operatorQueue: "Hàng chờ quản trị",
  customRequestTitle: "Yêu cầu riêng",
  customRequestCopy: "Không thấy phần thưởng phù hợp? Gửi yêu cầu cho quản trị viên. Một vé được giữ khi gửi và hoàn lại nếu yêu cầu bị từ chối.",
  requestContent: "Nội dung yêu cầu",
  requestPlaceholder: "Ví dụ: Tôi muốn 20 sách kinh nghiệm để nâng đội hình.",
  requestMeta: "1 vé · {count}/500",
  sendRequest: "Gửi yêu cầu",
  recentRequests: "Yêu cầu gần đây",
  requestRefreshFailed: "Không thể cập nhật yêu cầu.",
  noRequests: "Chưa có yêu cầu nào.",
  pending: "Đang chờ",
  approved: "Đã duyệt",
  denied: "Đã từ chối",
  keepRealm: "Giữ vương quốc hoạt động",
  donateTitle: "Ủng hộ máy chủ",
  donateCopy: "Cảm ơn bạn đã ủng hộ. Vé là quà tặng do quản trị viên quyết định, không phải điều kiện hay giá trị quy đổi bắt buộc.",
  donatePageCopy: "Mọi khoản ủng hộ đều tự nguyện. Vé là quà tặng do quản trị viên xét thủ công, không phải giá trị quy đổi hay điều kiện bắt buộc.",
  instructionsPending: "Hướng dẫn chuyển khoản đang được cập nhật.",
  donationNote: "Ghi chú sau khi ủng hộ",
  donationPlaceholder: "Ví dụ: Đã chuyển MoMo, mã giao dịch 1234.",
  donationSending: "Đang gửi…",
  donationAction: "Tôi đã ủng hộ",
  securityNote: "Lưu ý bảo mật",
  passwordTitle: "Đổi mật khẩu tạm",
  passwordCopy: "Việc này sẽ đăng xuất các phiên cũ để bảo vệ save game của bạn.",
  currentPassword: "Mật khẩu hiện tại",
  newPassword: "Mật khẩu mới, ít nhất 8 ký tự",
  updating: "Đang cập nhật…",
  changePassword: "Đổi mật khẩu",
  playerAccessRequired: "Cần đăng nhập",
  loginBeforeDonate: "Đăng nhập trước khi gửi ghi chú.",
  loginBeforeDonateCopy: "Chúng tôi chỉ lưu ghi chú vào đúng tài khoản game của bạn.",
  openDashboard: "Mở Player Dashboard",
  errorRequest: "Yêu cầu không thành công. Vui lòng thử lại.",
  errorNoTickets: "Bạn không còn đủ vé.",
  errorWrongCredentials: "Tên đăng nhập hoặc mật khẩu không đúng.",
  errorRateLimited: "Đăng nhập sai quá nhiều lần. Hãy thử lại sau 10 phút.",
  errorAccountGone: "Tài khoản game không còn khả dụng.",
  errorCurrentPassword: "Mật khẩu hiện tại không đúng.",
  errorPasswordLength: "Mật khẩu mới phải có ít nhất 8 ký tự.",
  errorRequestLength: "Yêu cầu phải có từ 1 đến 500 ký tự.",
  errorDonationLength: "Ghi chú phải có từ 1 đến 1.000 ký tự.",
  errorEnterGame: "Hãy vào game trước khi sử dụng tính năng này.",
  errorReward: "Phần thưởng đã chọn không hợp lệ.",
  errorSignIn: "Hãy đăng nhập vào Player Dashboard.",
  errorGoogleUnavailable: "Đăng nhập Google chưa được cấu hình.",
  errorCrossSite: "Yêu cầu từ trang khác đã bị từ chối.",
  errorWalletFull: "Kho vé của bạn đã đầy.",
  errorDailyLimit: "Bạn đã đạt giới hạn vé hôm nay.",
  errorCooldown: "Vui lòng chờ trước khi nhận thêm vé.",
} as const

export type PortalMessageKey = keyof typeof vi
export type PortalTranslator = (key: PortalMessageKey, values?: TranslationValues) => string

const en: Record<PortalMessageKey, string> = {
  languageLabel: "Language",
  brandTagline: "King Bug Castle · private realm",
  online: "online",
  playerLedger: "Player ledger",
  patronDesk: "Patron desk",
  backLedger: "Back to player ledger",
  loadingLedger: "Opening player ledger…",
  loadingDonate: "Opening patron desk…",
  playerAccess: "Player access",
  welcomeLead: "Return to",
  welcomeEmphasis: "your kingdom.",
  welcomeCopy: "Open the right game save, exchange tickets for rewards, and receive them in your in-game mailbox.",
  googleRequirement: "Your Google account must have signed in to the game before.",
  continueGoogle: "Continue with Google",
  guestAccess: "Guest access",
  guestTitle: "Sign in with your access code",
  guestCopy: "An administrator issues a username and temporary password after verifying your game account.",
  username: "Username",
  password: "Password",
  openingLedger: "Opening ledger…",
  signIn: "Sign in",
  tempPasswordPrompt: "Please replace your temporary password.",
  loginFailed: "Could not sign in.",
  passwordChanged: "Password changed. Please sign in again.",
  passwordChangeFailed: "Could not change your password.",
  rewardSent: "Used 1 ticket and sent {reward} to your in-game mailbox.",
  lastRewardSent: "Sent {reward} to your in-game mailbox. You have no tickets left.",
  redeemFailed: "Could not redeem the ticket.",
  requestSubmitted: "Request sent. 1 ticket is being held for this request.",
  requestFailed: "Could not send your request.",
  donationSubmitted: "Support note sent. An administrator will review it manually.",
  donationPageSubmitted: "Note sent. An administrator will review it and decide on any gift manually.",
  donationFailed: "Could not send your note.",
  linkedPlayerAria: "Player information",
  linkedPlayer: "Linked player",
  signOut: "Sign out",
  ticketReserve: "Ticket reserve",
  ticketTitle: "Your tickets",
  ticketCopy: "Video ticket rewards are temporarily disabled to protect player balances.",
  ticketLoading: "Loading wallet…",
  ticketUnit: "tickets",
  today: "Today",
  refresh: "Refresh",
  ticketRefreshFailed: "Could not refresh your tickets.",
  cooldown: "The next claim opens in {minutes} minutes.",
  videoDisabled: "Video ticket rewards are temporarily disabled",
  claimEyebrow: "Claim by mail",
  claimTitle: "Redeem and receive",
  claimCopy: "Each claim costs one ticket. Your reward will wait in your in-game mailbox.",
  reward: "Reward",
  useTicket: "Use 1 ticket",
  confirmReward: "Send {reward} to your in-game mailbox?",
  sending: "Sending…",
  confirm: "Confirm",
  cancel: "Cancel",
  catalogLoading: "Loading reward catalog…",
  operatorQueue: "Administrator queue",
  customRequestTitle: "Custom request",
  customRequestCopy: "Cannot find the right reward? Send a request to an administrator. One ticket is held when you submit and refunded if the request is denied.",
  requestContent: "Request details",
  requestPlaceholder: "Example: I would like 20 experience books for my team.",
  requestMeta: "1 ticket · {count}/500",
  sendRequest: "Send request",
  recentRequests: "Recent requests",
  requestRefreshFailed: "Could not refresh your requests.",
  noRequests: "No requests yet.",
  pending: "Pending",
  approved: "Approved",
  denied: "Denied",
  keepRealm: "Keep the realm alive",
  donateTitle: "Support the server",
  donateCopy: "Thank you for supporting the server. Tickets are optional gifts decided by an administrator, not a required exchange or purchase.",
  donatePageCopy: "All support is voluntary. Tickets are gifts reviewed manually by an administrator, not a required exchange or purchase.",
  instructionsPending: "Transfer instructions are being updated.",
  donationNote: "Note after supporting",
  donationPlaceholder: "Example: Sent via MoMo, transaction reference 1234.",
  donationSending: "Sending…",
  donationAction: "I have supported",
  securityNote: "Security note",
  passwordTitle: "Replace temporary password",
  passwordCopy: "This signs out older sessions to protect your game save.",
  currentPassword: "Current password",
  newPassword: "New password, at least 8 characters",
  updating: "Updating…",
  changePassword: "Change password",
  playerAccessRequired: "Player access required",
  loginBeforeDonate: "Sign in before sending a note.",
  loginBeforeDonateCopy: "We only save the note to your linked game account.",
  openDashboard: "Open Player Dashboard",
  errorRequest: "The request failed. Please try again.",
  errorNoTickets: "You do not have enough tickets.",
  errorWrongCredentials: "The username or password is incorrect.",
  errorRateLimited: "Too many failed sign-in attempts. Try again in 10 minutes.",
  errorAccountGone: "The game account is no longer available.",
  errorCurrentPassword: "The current password is incorrect.",
  errorPasswordLength: "The new password must be at least 8 characters.",
  errorRequestLength: "The request must be between 1 and 500 characters.",
  errorDonationLength: "The note must be between 1 and 1,000 characters.",
  errorEnterGame: "Enter the game before using this feature.",
  errorReward: "The selected reward is invalid.",
  errorSignIn: "Sign in to the Player Dashboard.",
  errorGoogleUnavailable: "Google sign-in is not configured.",
  errorCrossSite: "A request from another site was refused.",
  errorWalletFull: "Your ticket wallet is full.",
  errorDailyLimit: "You have reached today's ticket limit.",
  errorCooldown: "Please wait before earning another ticket.",
}

const dictionaries = { vi, en }
const STORAGE_KEY = "kgc-player-locale"
const CHANGE_EVENT = "kgc-player-locale-change"

const errorKeys: Record<string, PortalMessageKey> = {
  "Request failed": "errorRequest",
  request_failed: "errorRequest",
  insufficient_tickets: "errorNoTickets",
  "wrong username or password": "errorWrongCredentials",
  "too many sign-in attempts; wait 10 minutes": "errorRateLimited",
  "game account is no longer available": "errorAccountGone",
  "current password is wrong": "errorCurrentPassword",
  "new password must be at least 8 characters": "errorPasswordLength",
  "request text must be between 1 and 500 characters": "errorRequestLength",
  "donation note must be between 1 and 1000 characters": "errorDonationLength",
  "enter the game before submitting a request": "errorEnterGame",
  "enter the game before claiming a portal reward": "errorEnterGame",
  "invalid reward selection": "errorReward",
  "reward amount is outside the allowed range": "errorReward",
  "reward is not available in the player catalog": "errorReward",
  "sign in to the player portal": "errorSignIn",
  "Google sign-in is not configured": "errorGoogleUnavailable",
  "cross-site portal request refused": "errorCrossSite",
  wallet_full: "errorWalletFull",
  daily_limit: "errorDailyLimit",
  cooldown: "errorCooldown",
}

const grantCopy: Record<PortalLocale, Record<string, { name: string; note: string }>> = {
  vi: {
    "Gold:0": { name: "Vàng", note: "Tài nguyên cơ bản để phát triển vương quốc." },
    "Heart:0": { name: "Thể lực", note: "Năng lượng dùng để tham gia các trận đấu." },
    "Item:100": { name: "EXP Anh Hùng", note: "Kinh nghiệm để nâng cấp anh hùng." },
    "Item:150": { name: "Mảnh Tăng Trưởng", note: "Vật phẩm hỗ trợ tăng trưởng anh hùng." },
  },
  en: {
    "Gold:0": { name: "Gold", note: "Core currency for developing your kingdom." },
    "Heart:0": { name: "Heart", note: "Energy used to enter battles." },
    "Item:100": { name: "Hero EXP", note: "Experience used to level up heroes." },
    "Item:150": { name: "Shard of Growth", note: "An item that supports hero growth." },
  },
}

function browserLocale(): PortalLocale {
  if (typeof window === "undefined") return "vi"
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved === "vi" || saved === "en") return saved
  } catch {}
  return window.navigator.language.toLowerCase().startsWith("vi") ? "vi" : "en"
}

function subscribeLocale(onStoreChange: () => void) {
  if (typeof window === "undefined") return () => undefined
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) onStoreChange()
  }
  window.addEventListener("storage", onStorage)
  window.addEventListener(CHANGE_EVENT, onStoreChange)
  return () => {
    window.removeEventListener("storage", onStorage)
    window.removeEventListener(CHANGE_EVENT, onStoreChange)
  }
}

function translate(locale: PortalLocale, key: PortalMessageKey, values?: TranslationValues) {
  return dictionaries[locale][key].replace(/\{(\w+)\}/g, (token, name) =>
    values?.[name] === undefined ? token : String(values[name]))
}

type PortalLocaleContextValue = {
  locale: PortalLocale
  setLocale: (locale: PortalLocale) => void
  t: PortalTranslator
  errorMessage: (cause: unknown, fallback: PortalMessageKey) => string
}

const PortalLocaleContext = createContext<PortalLocaleContextValue | null>(null)

export function PortalLocaleProvider({ children }: { children: React.ReactNode }) {
  const locale = useSyncExternalStore<PortalLocale>(subscribeLocale, browserLocale, () => "vi")
  const t: PortalTranslator = (key, values) => translate(locale, key, values)

  useEffect(() => {
    const previous = document.documentElement.lang
    document.documentElement.lang = locale
    document.documentElement.dataset.portalLocale = locale
    return () => {
      document.documentElement.lang = previous
      delete document.documentElement.dataset.portalLocale
    }
  }, [locale])

  const setLocale = (next: PortalLocale) => {
    try { window.localStorage.setItem(STORAGE_KEY, next) } catch {}
    window.dispatchEvent(new Event(CHANGE_EVENT))
  }

  const errorMessage = (cause: unknown, fallback: PortalMessageKey) => {
    const raw = cause instanceof Error ? cause.message : ""
    const known = errorKeys[raw]
    if (known) return t(known)
    return locale === "en" && raw ? raw : t(fallback)
  }

  return <PortalLocaleContext.Provider value={{ locale, setLocale, t, errorMessage }}>{children}</PortalLocaleContext.Provider>
}

export function usePortalLocale() {
  const context = useContext(PortalLocaleContext)
  if (!context) throw new Error("usePortalLocale must be used within PortalLocaleProvider")
  return context
}

export function localizePortalGrant(
  locale: PortalLocale,
  type: string,
  id: number,
  fallbackName: string,
  fallbackNote: string,
) {
  return grantCopy[locale][`${type}:${id}`] || { name: fallbackName, note: fallbackNote }
}

export function PortalLanguageSwitch() {
  const { locale, setLocale, t } = usePortalLocale()
  return <div className="portal-language-switch" role="group" aria-label={t("languageLabel")}>
    {(["vi", "en"] as const).map(option => <button
      key={option}
      type="button"
      className="portal-language-option"
      aria-pressed={locale === option}
      title={option === "vi" ? "Tiếng Việt" : "English"}
      onClick={() => setLocale(option)}
    >{option.toUpperCase()}</button>)}
  </div>
}
