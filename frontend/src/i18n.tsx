import { createContext, useContext, useEffect, useMemo, useState } from 'react';

/**
 * Lightweight i18n: no runtime dependency, no build step.
 *
 * The English dictionary is the source of truth for the key type; the Russian
 * one is checked against it by TypeScript (`Record<TKey, string>`), so a
 * missing translation fails `tsc` instead of silently falling back at runtime.
 *
 * Switching the language only changes React state: every component that calls
 * `useI18n()` re-renders immediately, no reload required.
 */
export type Lang = 'ru' | 'en';

export const LANGS: Lang[] = ['ru', 'en'];

const en = {
  // Navigation / shell
  'nav.devices': 'Devices',
  'nav.books': 'Address Books',
  'nav.tags': 'Tags',
  'nav.users': 'Users',
  'nav.mobile': 'Mobile navigation',
  'shell.selfHosted': 'Self-hosted RustDesk API',
  'shell.developedBy': 'Developed by',
  'brand.subtitle': 'Address Book Panel by',
  'theme.toLight': 'Switch to light theme',
  'theme.toDark': 'Switch to dark theme',
  'theme.toggle': 'Toggle theme',
  'lang.label': 'Language',
  'auth.logout': 'Logout',

  // Common
  'common.cancel': 'Cancel',
  'common.save': 'Save',
  'common.saving': 'Saving…',
  'common.working': 'Working…',
  'common.create': 'Create',
  'common.delete': 'Delete',
  'common.remove': 'Remove',
  'common.edit': 'Edit',
  'common.rename': 'Rename',
  'common.retry': 'Retry',
  'common.close': 'Close',
  'common.password': 'Password',
  'common.previous': 'Previous',
  'common.next': 'Next',
  'common.notReported': 'Not reported',
  'common.loadFailed': 'Failed to load',

  // Login
  'login.signIn': 'Sign in',
  'login.hint': 'Use your address book account.',
  'login.username': 'username',
  'login.password': 'password',
  'login.usernameLabel': 'Username',
  'login.passwordLabel': 'Password',
  'login.submit': 'Login',

  // Profile dialog
  'profile.title': 'Profile',
  'profile.subtitle': 'The name other PCs see when you connect',
  'profile.displayName': 'Display name',
  'profile.placeholder': 'Leave empty to use your login name',
  'profile.hint':
    'Sent to the remote PC when you connect. RustDesk picks it up after your next sign-in.',
  'profile.saved': 'Display name saved',

  // Presence / relative time
  'status.online': 'Online',
  'status.lastSeen': 'Last seen {time}',
  'status.unknown': 'Last seen — Unknown',
  'time.unknown': 'Unknown',
  'time.justNow': 'just now',
  'time.minAgo': '{n} min ago',
  'time.hoursAgo': '{n}h ago',
  'time.yesterday': 'yesterday',
  'time.daysAgo': '{n} days ago',

  // Books page
  'books.title': 'Address Books',
  'books.create': '+ Create',
  'books.loading': 'Loading books',
  'books.openTitle': 'Open devices',
  'books.typePersonal': 'personal',
  'books.typeShared': 'shared',
  'books.typeOther': '{type}',
  'books.personalNote': ' (name shown by client is fixed)',
  'books.stats': '{devices} devices · 🟢 {online} · ⚪ {offline}',
  'books.statsUnknown': ' · ? {n}',
  'books.created': 'Address book created',
  'books.renamed': 'Address book renamed',
  'books.deleted': 'Address book deleted',
  'books.renameTitle': 'Rename address book',
  'books.createTitle': 'Create address book',
  'books.namePlaceholder': 'Shared book name',
  'books.deleteConfirm': 'Delete "{name}" with all its devices and tags?',

  // Tags page
  'tags.title': 'Tags',
  'tags.create': '+ Create tag',
  'tags.loading': 'Loading tags',
  'tags.name': 'Name',
  'tags.color': 'Color',
  'tags.devices': 'Devices',
  'tags.empty': 'No tags yet',
  'tags.changeColor': 'Change color',
  'tags.created': 'Tag created',
  'tags.colorSaved': 'Color saved',
  'tags.renamed': 'Tag renamed',
  'tags.deleted': 'Tag deleted',
  'tags.renameTitle': 'Rename tag',
  'tags.createTitle': 'Create tag',
  'tags.namePlaceholder': 'Tag name',
  'tags.deleteConfirm': 'Delete tag "{name}"? Devices stay, links are removed.',
  'tags.bookLabel': 'Address book',

  // Users page
  'users.title': 'Users',
  'users.add': '+ Add user',
  'users.loading': 'Loading users',
  'users.username': 'Username',
  'users.displayName': 'Display name',
  'users.role': 'Role',
  'users.status': 'Status',
  'users.admin': 'admin',
  'users.user': 'user',
  'users.disabled': 'disabled',
  'users.active': 'active',
  'users.toggleRole': 'Toggle role',
  'users.toggleStatus': 'Toggle status',
  'users.required': 'Username and password required',
  'users.usernameRequired': 'Username required',
  'users.created': 'User created',
  'users.updated': 'User updated',
  'users.deleted': 'User deleted',
  'users.roleUpdated': 'Role updated',
  'users.enabled': 'User enabled',
  'users.disabledMsg': 'User disabled',
  'users.addTitle': 'Add user',
  'users.editTitle': 'Edit user',
  'users.usernamePlaceholder': 'username',
  'users.displayPlaceholder': 'display name (optional)',
  'users.passwordPlaceholder': 'password',
  'users.newPasswordPlaceholder': 'new password (leave empty to keep)',
  'users.deleteConfirm': 'Delete user "{name}"?',

  // Devices page: header, tabs, filters
  'dev.title': 'Devices',
  'dev.subtitle': 'Address books, server discovery and client-reported system details.',
  'dev.stats': '{online} online · {offline} offline',
  'dev.statsUnknown': ' · {n} unknown',
  'dev.statsDiscovered': ' · discovered {online}/{total}',
  'dev.add': '+ Add device',
  'dev.tabAll': 'All devices',
  'dev.tabBook': 'Address book',
  'dev.tabDiscovered': 'Discovered',
  'dev.selectBook': 'Address book',
  'dev.readOnly': ' (read-only)',
  'dev.searchPlaceholder': 'Search ID, hostname, user, note…',
  'dev.sortLabel': 'Sort devices',
  'dev.sortTitle': 'Sort',
  'dev.sortStatus': 'Status + Alias',
  'dev.sortAlias': 'Alias',
  'dev.sortId': 'RustDesk ID',
  'dev.sortLastSeen': 'Last seen',
  'dev.presenceFilter': 'Presence filter',
  'dev.allStates': 'All states',
  'dev.online': 'Online',
  'dev.offline': 'Offline',
  'dev.unknown': 'Unknown',
  'dev.discoveryStatus': 'Discovery status',
  'dev.allDiscovered': 'All discovered',
  'dev.discoveredOnline': 'Discovered online',
  'dev.discoveredOffline': 'Discovered offline',
  'dev.clearFilters': 'Clear filters',
  'dev.allTags': 'All tags',
  'dev.tagDevices': '{n} device(s)',
  'dev.matchMode': 'Match all selected tags or any of them',
  'dev.refreshFailed': 'Refresh failed — showing the previous result.',
  'dev.discoveryRefreshFailed': 'Discovery refresh failed — showing the previous result.',
  'dev.updating': 'Updating…',
  'dev.selected': '{n} selected',
  'dev.addRemoveTags': 'Add / remove tags',
  'dev.clearSelection': 'Clear selection',

  // Devices page: lists
  'dev.loadingDevices': 'Loading devices',
  'dev.loadingDiscovered': 'Loading discovered devices',
  'dev.noMatchFilters': 'No devices match the current filters.',
  'dev.emptyBook': 'This address book is empty.',
  'dev.addFirst': 'Add your first device',
  'dev.noDiscoveredMatch': 'No discovered devices match the current filters.',
  'dev.noDiscoveredOutside':
    'No discovered devices outside your address books. Devices seen by the server but already in a visible book are hidden here.',
  'dev.noDevicesConnected': 'No devices have connected to this server yet.',
  'dev.discoveryExplainer':
    'Discovery uses the RustDesk rendezvous connection seen by the server. Clients do not need an API address for this part. System details appear only when a client also uploads them to the API.',
  'dev.selectAllPage': 'Select all on this page',
  'dev.selectAllDevices': 'Select all devices on this page',
  'dev.selectOne': 'Select {name}',
  'dev.infoBadge': 'info',
  'dev.infoBadgeTitle': 'The client uploaded system information',
  'dev.osIpNotReported': 'OS and IP not reported',
  'dev.osVersionIpNotReported': 'OS, client version and IP not reported',
  'dev.noSysinfo': 'no sysinfo',
  'dev.noSysinfoTitle': 'The client has not uploaded system information',
  'dev.inBook': 'In book: {books}',
  'dev.addToBook': 'Add to book',
  'dev.firstSeenVia': '· first seen {time}',
  'dev.via': '· via {source}',

  // Devices page: sections and actions
  'dev.sectionBook': 'Address book',
  'dev.sectionBookReadOnly': ' · read-only',
  'dev.discoveredNotInBooks': 'Discovered, not in your address books',
  'dev.discoveredDevices': 'Discovered devices',
  'dev.discoveredSubtitleAll':
    'Seen by the RustDesk server but not linked to a visible address book.',
  'dev.discoveredSubtitle':
    'Rendezvous evidence from the server, including devices already in address books.',
  'dev.discoveryNote':
    'Discovery needs no client API setting. Hostname, OS and hardware details require a custom API server on the client.',
  'dev.selectBookFirst': 'Select an address book first',
  'dev.removeConfirm':
    'Remove {name} from the address book? Tags themselves are not deleted.',
  'dev.bulkDeleteConfirm':
    'Delete {n} selected device(s) from the address book? Tags themselves are not deleted.',
  'dev.removedFromBook': 'Removed from address book',
  'dev.deletedCount': 'Deleted {n} device(s)',
  'dev.deleteFailedCount':
    '{n} device(s) could not be deleted (permission or already gone)',
  'dev.tagsUpdatedCount': 'Updated tags on {n} device(s)',
  'dev.tagsFailedCount':
    '{n} device(s) were not updated (permission or already gone)',
  'dev.addedToBook': 'Added {id} to the address book',

  // Devices page: detail drawer
  'dev.loadingDevice': 'Loading device',
  'dev.noData': 'No data.',
  'dev.device': 'Device {id}',
  'dev.connection': 'Connection',
  'dev.status': 'Status',
  'dev.lastSeen': 'Last seen',
  'dev.ip': 'IP address',
  'dev.detectedVia': 'Detected via',
  'dev.addressBookHeartbeat': 'Address book heartbeat',
  'dev.notAvailable': 'Not available',
  'dev.firstSeen': 'First seen',
  'dev.lastConnected': 'Last connected',
  'dev.lastDisconnected': 'Last disconnected',
  'dev.addressBooks': 'Address books',
  'dev.notInVisibleBook': 'Not in a visible book',
  'dev.system': 'System',
  'dev.hostname': 'Hostname',
  'dev.username': 'Username',
  'dev.operatingSystem': 'Operating system',
  'dev.osFamily': 'OS family',
  'dev.osVersion': 'OS version',
  'dev.clientVersion': 'Client version',
  'dev.clientReport': 'Client report',
  'dev.reportUploaded': 'Report uploaded',
  'dev.lastHeartbeat': 'Last heartbeat',
  'dev.noHeartbeat': 'No heartbeat received',
  'dev.hardware': 'Hardware',
  'dev.cpu': 'CPU',
  'dev.frequency': 'Frequency',
  'dev.cores': 'Cores',
  'dev.totalRam': 'Total RAM',
  'dev.notProvidedTitle': 'Not provided by the stock RustDesk client',
  'dev.fieldArchitecture': 'Architecture',
  'dev.fieldRamUsage': 'RAM usage',
  'dev.fieldGpu': 'GPU',
  'dev.fieldDisks': 'Disks',
  'dev.fieldNetwork': 'Network adapters',
  'dev.notProvidedNote':
    'The client uploads hostname, username, OS, CPU model/cores, total RAM and its version. These fields stay unavailable instead of being guessed.',
  'dev.storedPassword': 'Stored password configured',
  'dev.noStoredPassword': 'No stored password',
  'dev.refreshInfo': 'Refresh info',
  'dev.forget': 'Forget',
  'dev.noWritableBooks': 'You have no writable address books',
  'dev.forgetConfirm':
    'Remove the discovery record for {id}? Address book entries and the stored system report are not deleted.',
  'dev.discoveryRemoved': 'Discovery record removed',
  'dev.refreshOnline':
    'Refresh requested. The client will report on its next heartbeat (about 15 s).',
  'dev.refreshOffline':
    'Refresh requested. It will apply when the device reconnects (within 30 minutes).',
  'dev.coresLogical': '{n} logical',
  'dev.coresPhysical': '{n} physical',
  'dev.coresBoth': '{logical} logical / {physical} physical',

  // Devices page: freshness badge
  'dev.freshNo': 'No system report',
  'dev.freshNoTitle': 'This client has not uploaded system information.',
  'dev.freshStale': 'Stale report',
  'dev.freshFresh': 'Fresh report',
  'dev.lastUploaded': 'Last uploaded {time}',

  // Devices page: add discovered modal
  'dev.addDiscoveredTitle': 'Add discovered device',
  'dev.addDiscoveredSubtitle':
    'The device stays in the discovered registry; a copy is added to the selected book.',
  'dev.adding': 'Adding…',
  'dev.noWriteAccess': 'You do not have write access to any address book.',
  'dev.chooseBook': 'Choose an address book.',
  'dev.alias': 'Alias',
  'dev.note': 'Note',
  'dev.tags': 'Tags',
  'dev.noTagsBook': 'No tags in this book yet',
  'dev.noTagsBookShort': 'No tags in this book',
  'dev.loadingTags': 'Loading tags…',
  'dev.newTagsPlaceholder': 'New tags, comma separated',
  'dev.tag': 'Tag {name}',
  'dev.addTag': 'Add {name}',
  'dev.removeTag': 'Remove {name}',

  // Devices page: bulk tag modal
  'dev.bulkTagsTitle': 'Add or remove tags',
  'dev.bulkTagsSubtitle':
    '{n} selected. Existing tags are preserved; only the checked tags change.',
  'dev.selectOneTag': 'Select or type at least one tag.',
  'dev.tagOverlap': 'Tag "{name}" is selected for both adding and removing.',
  'dev.addTags': 'Add tags',
  'dev.removeTags': 'Remove tags',
  'dev.tagDetachNote':
    'A tag is only detached from the selected devices; the tag itself is not deleted.',
  'dev.upTo20': 'Up to 20 tags per operation.',
  'dev.applying': 'Applying…',
  'dev.apply': 'Apply',

  // Devices page: device form
  'dev.editDevice': 'Edit device',
  'dev.addDevice': 'Add device',
  'dev.rustdeskId': 'RustDesk ID',
  'dev.rustdeskIdRequired': 'RustDesk ID required',
  'dev.tagsStillLoading': 'Tags are still loading; try again in a moment.',
  'dev.deviceUpdated': 'Device updated',
  'dev.deviceCreated': 'Device created',
  'dev.passwordKeep': '(leave empty to keep)',
} as const;

export type TKey = keyof typeof en;

const ru: Record<TKey, string> = {
  'nav.devices': 'Устройства',
  'nav.books': 'Адресные книги',
  'nav.tags': 'Теги',
  'nav.users': 'Пользователи',
  'nav.mobile': 'Мобильная навигация',
  'shell.selfHosted': 'Self-hosted RustDesk API',
  'shell.developedBy': 'Разработчик',
  'brand.subtitle': 'Панель адресной книги от',
  'theme.toLight': 'Включить светлую тему',
  'theme.toDark': 'Включить тёмную тему',
  'theme.toggle': 'Переключить тему',
  'lang.label': 'Язык',
  'auth.logout': 'Выйти',

  'common.cancel': 'Отмена',
  'common.save': 'Сохранить',
  'common.saving': 'Сохранение…',
  'common.working': 'Выполняется…',
  'common.create': 'Создать',
  'common.delete': 'Удалить',
  'common.remove': 'Убрать',
  'common.edit': 'Изменить',
  'common.rename': 'Переименовать',
  'common.retry': 'Повторить',
  'common.close': 'Закрыть',
  'common.password': 'Пароль',
  'common.previous': 'Назад',
  'common.next': 'Далее',
  'common.notReported': 'Не передано',
  'common.loadFailed': 'Не удалось загрузить',

  'login.signIn': 'Вход',
  'login.hint': 'Используйте учётную запись адресной книги.',
  'login.username': 'логин',
  'login.password': 'пароль',
  'login.usernameLabel': 'Имя пользователя',
  'login.passwordLabel': 'Пароль',
  'login.submit': 'Войти',

  'profile.title': 'Профиль',
  'profile.subtitle': 'Имя, которое видят другие ПК при подключении',
  'profile.displayName': 'Отображаемое имя',
  'profile.placeholder': 'Оставьте пустым, чтобы использовать логин',
  'profile.hint':
    'Передаётся на удалённый ПК при подключении. RustDesk применит его после следующего входа.',
  'profile.saved': 'Отображаемое имя сохранено',

  'status.online': 'В сети',
  'status.lastSeen': 'Последняя активность: {time}',
  'status.unknown': 'Последняя активность: неизвестно',
  'time.unknown': 'Неизвестно',
  'time.justNow': 'только что',
  'time.minAgo': '{n} мин назад',
  'time.hoursAgo': '{n} ч назад',
  'time.yesterday': 'вчера',
  'time.daysAgo': '{n} дн. назад',

  'books.title': 'Адресные книги',
  'books.create': '+ Создать',
  'books.loading': 'Загрузка книг',
  'books.openTitle': 'Открыть устройства',
  'books.typePersonal': 'личная',
  'books.typeShared': 'общая',
  'books.typeOther': '{type}',
  'books.personalNote': ' (имя в клиенте фиксировано)',
  'books.stats': '{devices} устройств · 🟢 {online} · ⚪ {offline}',
  'books.statsUnknown': ' · ? {n}',
  'books.created': 'Адресная книга создана',
  'books.renamed': 'Адресная книга переименована',
  'books.deleted': 'Адресная книга удалена',
  'books.renameTitle': 'Переименовать адресную книгу',
  'books.createTitle': 'Создать адресную книгу',
  'books.namePlaceholder': 'Название общей книги',
  'books.deleteConfirm': 'Удалить «{name}» со всеми устройствами и тегами?',

  'tags.title': 'Теги',
  'tags.create': '+ Создать тег',
  'tags.loading': 'Загрузка тегов',
  'tags.name': 'Название',
  'tags.color': 'Цвет',
  'tags.devices': 'Устройства',
  'tags.empty': 'Тегов пока нет',
  'tags.changeColor': 'Изменить цвет',
  'tags.created': 'Тег создан',
  'tags.colorSaved': 'Цвет сохранён',
  'tags.renamed': 'Тег переименован',
  'tags.deleted': 'Тег удалён',
  'tags.renameTitle': 'Переименовать тег',
  'tags.createTitle': 'Создать тег',
  'tags.namePlaceholder': 'Название тега',
  'tags.deleteConfirm': 'Удалить тег «{name}»? Устройства останутся, связи будут удалены.',
  'tags.bookLabel': 'Адресная книга',

  'users.title': 'Пользователи',
  'users.add': '+ Добавить пользователя',
  'users.loading': 'Загрузка пользователей',
  'users.username': 'Логин',
  'users.displayName': 'Отображаемое имя',
  'users.role': 'Роль',
  'users.status': 'Статус',
  'users.admin': 'админ',
  'users.user': 'пользователь',
  'users.disabled': 'отключён',
  'users.active': 'активен',
  'users.toggleRole': 'Переключить роль',
  'users.toggleStatus': 'Переключить статус',
  'users.required': 'Требуются логин и пароль',
  'users.usernameRequired': 'Требуется логин',
  'users.created': 'Пользователь создан',
  'users.updated': 'Пользователь обновлён',
  'users.deleted': 'Пользователь удалён',
  'users.roleUpdated': 'Роль обновлена',
  'users.enabled': 'Пользователь включён',
  'users.disabledMsg': 'Пользователь отключён',
  'users.addTitle': 'Добавить пользователя',
  'users.editTitle': 'Изменить пользователя',
  'users.usernamePlaceholder': 'логин',
  'users.displayPlaceholder': 'отображаемое имя (необязательно)',
  'users.passwordPlaceholder': 'пароль',
  'users.newPasswordPlaceholder': 'новый пароль (оставьте пустым, чтобы не менять)',
  'users.deleteConfirm': 'Удалить пользователя «{name}»?',

  'dev.title': 'Устройства',
  'dev.subtitle': 'Адресные книги, обнаружение сервером и сведения от клиентов.',
  'dev.stats': '{online} в сети · {offline} не в сети',
  'dev.statsUnknown': ' · {n} неизвестно',
  'dev.statsDiscovered': ' · обнаружено {online}/{total}',
  'dev.add': '+ Добавить устройство',
  'dev.tabAll': 'Все устройства',
  'dev.tabBook': 'Адресная книга',
  'dev.tabDiscovered': 'Обнаруженные',
  'dev.selectBook': 'Адресная книга',
  'dev.readOnly': ' (только чтение)',
  'dev.searchPlaceholder': 'Поиск по ID, хосту, пользователю, заметке…',
  'dev.sortLabel': 'Сортировка устройств',
  'dev.sortTitle': 'Сортировка',
  'dev.sortStatus': 'Статус + псевдоним',
  'dev.sortAlias': 'Псевдоним',
  'dev.sortId': 'RustDesk ID',
  'dev.sortLastSeen': 'Последняя активность',
  'dev.presenceFilter': 'Фильтр по присутствию',
  'dev.allStates': 'Все состояния',
  'dev.online': 'В сети',
  'dev.offline': 'Не в сети',
  'dev.unknown': 'Неизвестно',
  'dev.discoveryStatus': 'Статус обнаружения',
  'dev.allDiscovered': 'Все обнаруженные',
  'dev.discoveredOnline': 'Обнаруженные в сети',
  'dev.discoveredOffline': 'Обнаруженные не в сети',
  'dev.clearFilters': 'Сбросить фильтры',
  'dev.allTags': 'Все теги',
  'dev.tagDevices': 'Устройств: {n}',
  'dev.matchMode': 'Совпадение по всем выбранным тегам или по любому из них',
  'dev.refreshFailed': 'Не удалось обновить — показан предыдущий результат.',
  'dev.discoveryRefreshFailed': 'Не удалось обновить обнаруженные — показан предыдущий результат.',
  'dev.updating': 'Обновление…',
  'dev.selected': 'Выбрано: {n}',
  'dev.addRemoveTags': 'Добавить / убрать теги',
  'dev.clearSelection': 'Снять выделение',

  'dev.loadingDevices': 'Загрузка устройств',
  'dev.loadingDiscovered': 'Загрузка обнаруженных устройств',
  'dev.noMatchFilters': 'Нет устройств, подходящих под текущие фильтры.',
  'dev.emptyBook': 'Эта адресная книга пуста.',
  'dev.addFirst': 'Добавить первое устройство',
  'dev.noDiscoveredMatch': 'Нет обнаруженных устройств, подходящих под текущие фильтры.',
  'dev.noDiscoveredOutside':
    'Нет обнаруженных устройств вне ваших адресных книг. Устройства, которые сервер видит, но которые уже есть в доступной книге, здесь скрыты.',
  'dev.noDevicesConnected': 'К этому серверу пока не подключалось ни одно устройство.',
  'dev.discoveryExplainer':
    'Обнаружение использует rendezvous-подключение RustDesk, которое видит сервер. Клиентам не нужен адрес API для этой части. Системные сведения появляются только если клиент также загружает их в API.',
  'dev.selectAllPage': 'Выбрать все на этой странице',
  'dev.selectAllDevices': 'Выбрать все устройства на этой странице',
  'dev.selectOne': 'Выбрать {name}',
  'dev.infoBadge': 'сведения',
  'dev.infoBadgeTitle': 'Клиент загрузил системные сведения',
  'dev.osIpNotReported': 'ОС и IP не переданы',
  'dev.osVersionIpNotReported': 'ОС, версия клиента и IP не переданы',
  'dev.noSysinfo': 'нет сведений',
  'dev.noSysinfoTitle': 'Клиент не загрузил системные сведения',
  'dev.inBook': 'В книге: {books}',
  'dev.addToBook': 'Добавить в книгу',
  'dev.firstSeenVia': '· впервые замечено {time}',
  'dev.via': '· через {source}',

  'dev.sectionBook': 'Адресная книга',
  'dev.sectionBookReadOnly': ' · только чтение',
  'dev.discoveredNotInBooks': 'Обнаруженные, но не в ваших адресных книгах',
  'dev.discoveredDevices': 'Обнаруженные устройства',
  'dev.discoveredSubtitleAll':
    'Видны серверу RustDesk, но не привязаны к доступной адресной книге.',
  'dev.discoveredSubtitle':
    'Свидетельства rendezvous от сервера, включая устройства, уже добавленные в книги.',
  'dev.discoveryNote':
    'Для обнаружения не нужна настройка API на клиенте. Имя хоста, ОС и сведения об оборудовании требуют указать на клиенте адрес этого API.',
  'dev.selectBookFirst': 'Сначала выберите адресную книгу',
  'dev.removeConfirm': 'Убрать {name} из адресной книги? Сами теги не удаляются.',
  'dev.bulkDeleteConfirm':
    'Удалить выбранные устройства ({n}) из адресной книги? Сами теги не удаляются.',
  'dev.removedFromBook': 'Убрано из адресной книги',
  'dev.deletedCount': 'Удалено устройств: {n}',
  'dev.deleteFailedCount':
    'Не удалось удалить устройств: {n} (нет прав или уже удалены)',
  'dev.tagsUpdatedCount': 'Теги обновлены у устройств: {n}',
  'dev.tagsFailedCount':
    'Не обновлены устройства: {n} (нет прав или уже удалены)',
  'dev.addedToBook': 'Устройство {id} добавлено в адресную книгу',

  'dev.loadingDevice': 'Загрузка устройства',
  'dev.noData': 'Нет данных.',
  'dev.device': 'Устройство {id}',
  'dev.connection': 'Подключение',
  'dev.status': 'Статус',
  'dev.lastSeen': 'Последняя активность',
  'dev.ip': 'IP-адрес',
  'dev.detectedVia': 'Источник',
  'dev.addressBookHeartbeat': 'Heartbeat адресной книги',
  'dev.notAvailable': 'Недоступно',
  'dev.firstSeen': 'Впервые замечено',
  'dev.lastConnected': 'Последнее подключение',
  'dev.lastDisconnected': 'Последнее отключение',
  'dev.addressBooks': 'Адресные книги',
  'dev.notInVisibleBook': 'Нет в доступных книгах',
  'dev.system': 'Система',
  'dev.hostname': 'Имя хоста',
  'dev.username': 'Пользователь',
  'dev.operatingSystem': 'Операционная система',
  'dev.osFamily': 'Семейство ОС',
  'dev.osVersion': 'Версия ОС',
  'dev.clientVersion': 'Версия клиента',
  'dev.clientReport': 'Отчёт клиента',
  'dev.reportUploaded': 'Отчёт загружен',
  'dev.lastHeartbeat': 'Последний heartbeat',
  'dev.noHeartbeat': 'Heartbeat не получен',
  'dev.hardware': 'Оборудование',
  'dev.cpu': 'CPU',
  'dev.frequency': 'Частота',
  'dev.cores': 'Ядра',
  'dev.totalRam': 'Объём RAM',
  'dev.notProvidedTitle': 'Не передаётся штатным клиентом RustDesk',
  'dev.fieldArchitecture': 'Архитектура',
  'dev.fieldRamUsage': 'Использование RAM',
  'dev.fieldGpu': 'GPU',
  'dev.fieldDisks': 'Диски',
  'dev.fieldNetwork': 'Сетевые адаптеры',
  'dev.notProvidedNote':
    'Клиент передаёт имя хоста, пользователя, ОС, модель и число ядер CPU, объём RAM и свою версию. Остальные поля остаются недоступными, а не угадываются.',
  'dev.storedPassword': 'Сохранённый пароль задан',
  'dev.noStoredPassword': 'Сохранённого пароля нет',
  'dev.refreshInfo': 'Обновить сведения',
  'dev.forget': 'Забыть',
  'dev.noWritableBooks': 'У вас нет адресных книг с правом записи',
  'dev.forgetConfirm':
    'Удалить запись обнаружения для {id}? Записи в адресных книгах и сохранённый системный отчёт не удаляются.',
  'dev.discoveryRemoved': 'Запись обнаружения удалена',
  'dev.refreshOnline':
    'Запрошено обновление. Клиент отчитается при следующем heartbeat (около 15 с).',
  'dev.refreshOffline':
    'Запрошено обновление. Оно применится, когда устройство снова подключится (в течение 30 минут).',
  'dev.coresLogical': 'логических: {n}',
  'dev.coresPhysical': 'физических: {n}',
  'dev.coresBoth': 'логических: {logical} / физических: {physical}',

  'dev.freshNo': 'Нет системного отчёта',
  'dev.freshNoTitle': 'Клиент не загружал системные сведения.',
  'dev.freshStale': 'Устаревший отчёт',
  'dev.freshFresh': 'Свежий отчёт',
  'dev.lastUploaded': 'Загружен {time}',

  'dev.addDiscoveredTitle': 'Добавить обнаруженное устройство',
  'dev.addDiscoveredSubtitle':
    'Устройство остаётся в реестре обнаруженных; копия добавляется в выбранную книгу.',
  'dev.adding': 'Добавление…',
  'dev.noWriteAccess': 'У вас нет прав записи ни в одну адресную книгу.',
  'dev.chooseBook': 'Выберите адресную книгу.',
  'dev.alias': 'Псевдоним',
  'dev.note': 'Заметка',
  'dev.tags': 'Теги',
  'dev.noTagsBook': 'В этой книге пока нет тегов',
  'dev.noTagsBookShort': 'В этой книге нет тегов',
  'dev.loadingTags': 'Загрузка тегов…',
  'dev.newTagsPlaceholder': 'Новые теги через запятую',
  'dev.tag': 'Тег {name}',
  'dev.addTag': 'Добавить {name}',
  'dev.removeTag': 'Убрать {name}',

  'dev.bulkTagsTitle': 'Добавить или убрать теги',
  'dev.bulkTagsSubtitle':
    'Выбрано: {n}. Существующие теги сохраняются; меняются только отмеченные.',
  'dev.selectOneTag': 'Выберите или введите хотя бы один тег.',
  'dev.tagOverlap': 'Тег «{name}» выбран одновременно для добавления и удаления.',
  'dev.addTags': 'Добавить теги',
  'dev.removeTags': 'Убрать теги',
  'dev.tagDetachNote':
    'Тег только отвязывается от выбранных устройств; сам тег не удаляется.',
  'dev.upTo20': 'Не более 20 тегов за операцию.',
  'dev.applying': 'Применение…',
  'dev.apply': 'Применить',

  'dev.editDevice': 'Изменить устройство',
  'dev.addDevice': 'Добавить устройство',
  'dev.rustdeskId': 'RustDesk ID',
  'dev.rustdeskIdRequired': 'Требуется RustDesk ID',
  'dev.tagsStillLoading': 'Теги ещё загружаются; повторите через момент.',
  'dev.deviceUpdated': 'Устройство обновлено',
  'dev.deviceCreated': 'Устройство добавлено',
  'dev.passwordKeep': '(оставьте пустым, чтобы не менять)',
};

const DICTS: Record<Lang, Record<TKey, string>> = { en, ru };

/** Translate outside React (e.g. helper functions that receive `lang`). */
export function translate(
  lang: Lang,
  key: TKey,
  vars?: Record<string, string | number>,
): string {
  let out = DICTS[lang][key] ?? en[key] ?? key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      out = out.split(`{${name}}`).join(String(value));
    }
  }
  return out;
}

type I18nValue = {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: TKey, vars?: Record<string, string | number>) => string;
};

const I18nContext = createContext<I18nValue | null>(null);

/** Stored choice wins; otherwise Russian, the primary language of this panel. */
function initialLang(): Lang {
  const saved = localStorage.getItem('ab_lang');
  return saved === 'en' || saved === 'ru' ? saved : 'ru';
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLang] = useState<Lang>(initialLang);

  useEffect(() => {
    document.documentElement.lang = lang;
    localStorage.setItem('ab_lang', lang);
  }, [lang]);

  const value = useMemo<I18nValue>(
    () => ({ lang, setLang, t: (key, vars) => translate(lang, key, vars) }),
    [lang],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used inside <I18nProvider>');
  return ctx;
}
