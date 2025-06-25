import React, { useState, useEffect, useRef } from 'react';
import { Activity, Settings, TrendingUp, AlertTriangle, BarChart3, Wifi, WifiOff, Clock, ChevronDown, ChevronRight, Trash2, Edit, Plus, X, Eye, EyeOff } from 'lucide-react';

interface Alert {
  id: number;
  price: number;
  volume_ratio: number;
  current_volume_usdt: number;
  average_volume_usdt: number;
  message: string;
  telegram_sent: boolean;
  created_at: string;
}

interface AlertGroup {
  id: number;
  symbol: string;
  alert_type: string;
  first_alert_time: string;
  last_alert_time: string;
  alert_count: number;
  max_volume_ratio: number;
  max_price: number;
  max_volume_usdt: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface WatchlistItem {
  id: number;
  symbol: string;
  is_active: boolean;
  price_drop_percentage: number;
  current_price: number;
  historical_price: number;
  created_at: string;
  updated_at: string;
}

interface LiveData {
  symbol: string;
  data: {
    open: string;
    high: string;
    low: string;
    close: string;
    volume: string;
  };
  timestamp: string;
  alert?: {
    symbol: string;
    volume_ratio: number;
    is_grouped: boolean;
    group_count: number;
  };
}

interface Stats {
  total_candles: number;
  long_candles: number;
  alerts_count: number;
  pairs_count: number;
  last_update: string;
}

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [alertGroups, setAlertGroups] = useState<AlertGroup[]>([]);
  const [expandedGroups, setExpandedGroups] = useState<Set<number>>(new Set());
  const [groupDetails, setGroupDetails] = useState<Map<number, Alert[]>>(new Map());
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [liveData, setLiveData] = useState<Map<string, LiveData>>(new Map());
  const [stats, setStats] = useState<Stats>({
    total_candles: 0,
    long_candles: 0,
    alerts_count: 0,
    pairs_count: 0,
    last_update: ''
  });
  const [activeTab, setActiveTab] = useState<'live' | 'watchlist' | 'alerts'>('live');
  const [showSettings, setShowSettings] = useState(false);
  const [showAddPair, setShowAddPair] = useState(false);
  const [newPairSymbol, setNewPairSymbol] = useState('');
  const [editingItem, setEditingItem] = useState<WatchlistItem | null>(null);
  const [settings, setSettings] = useState({
    volume_analyzer: {
      analysis_hours: 1,
      offset_minutes: 0,
      volume_multiplier: 2.0,
      min_volume_usdt: 1000,
      alert_grouping_minutes: 5
    },
    price_filter: {
      price_check_interval_minutes: 5,
      price_history_days: 30,
      price_drop_percentage: 10.0
    },
    telegram: {
      enabled: false
    }
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const notificationPermissionRef = useRef<boolean>(false);

  useEffect(() => {
    connectWebSocket();
    loadInitialData();
    requestNotificationPermission();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, []);

  const requestNotificationPermission = async () => {
    if ('Notification' in window) {
      const permission = await Notification.requestPermission();
      notificationPermissionRef.current = permission === 'granted';
    }
  };

  const showNotification = (title: string, body: string) => {
    if (notificationPermissionRef.current && (document.hidden || !document.hasFocus())) {
      new Notification(title, {
        body,
        icon: '/vite.svg',
        tag: 'volume-alert'
      });
    }
  };

  const connectWebSocket = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    wsRef.current = new WebSocket(wsUrl);

    wsRef.current.onopen = () => {
      console.log('WebSocket подключен');
      setIsConnected(true);
    };

    wsRef.current.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
      } catch (error) {
        console.error('Ошибка парсинга сообщения:', error);
      }
    };

    wsRef.current.onclose = () => {
      console.log('WebSocket отключен');
      setIsConnected(false);

      // Автоматическое переподключение через 5 секунд
      reconnectTimeoutRef.current = setTimeout(() => {
        connectWebSocket();
      }, 5000);
    };

    wsRef.current.onerror = (error) => {
      console.error('WebSocket ошибка:', error);
      setIsConnected(false);
    };
  };

  const handleWebSocketMessage = (data: any) => {
    switch (data.type) {
      case 'connection_status':
        setStats(prev => ({ ...prev, pairs_count: data.pairs_count }));
        break;
      case 'kline_update':
        setLiveData(prev => {
          const newMap = new Map(prev);
          newMap.set(data.symbol, data);
          return newMap;
        });

        if (data.alert) {
          // Показываем уведомление для новых алертов
          if (!data.alert.is_grouped) {
            showNotification(
              `Алерт по объему: ${data.alert.symbol}`,
              `Объем превышен в ${data.alert.volume_ratio}x раз`
            );
          }

          // Обновляем список групп алертов
          loadAlertGroups();
        }

        setStats(prev => ({
          ...prev,
          total_candles: prev.total_candles + 1,
          long_candles: parseFloat(data.data.close) > parseFloat(data.data.open)
            ? prev.long_candles + 1
            : prev.long_candles
        }));
        break;
      case 'watchlist_updated':
        loadWatchlist();
        break;
      case 'alert_deleted':
        setAlertGroups(prev => prev.filter(group => group.id !== data.group_id));
        setExpandedGroups(prev => {
          const newSet = new Set(prev);
          newSet.delete(data.group_id);
          return newSet;
        });
        setGroupDetails(prev => {
          const newMap = new Map(prev);
          newMap.delete(data.group_id);
          return newMap;
        });
        break;
      case 'alerts_cleared':
        setAlertGroups([]);
        setExpandedGroups(new Set());
        setGroupDetails(new Map());
        break;
    }
  };

  const loadInitialData = async () => {
    try {
      await Promise.all([
        loadWatchlist(),
        loadAlertGroups(),
        loadSettings(),
        loadStats()
      ]);
    } catch (error) {
      console.error('Ошибка загрузки данных:', error);
    }
  };

  const loadWatchlist = async () => {
    try {
      const response = await fetch('/api/watchlist');
      const data = await response.json();
      setWatchlist(data.pairs || []);
    } catch (error) {
      console.error('Ошибка загрузки watchlist:', error);
    }
  };

  const loadAlertGroups = async () => {
    try {
      const response = await fetch('/api/alerts');
      const data = await response.json();
      setAlertGroups(data.alert_groups || []);
    } catch (error) {
      console.error('Ошибка загрузки алертов:', error);
    }
  };

  const loadSettings = async () => {
    try {
      const response = await fetch('/api/settings');
      const data = await response.json();
      if (data.volume_analyzer && data.price_filter) {
        setSettings(data);
      }
    } catch (error) {
      console.error('Ошибка загрузки настроек:', error);
    }
  };

  const loadStats = async () => {
    try {
      const response = await fetch('/api/stats');
      const data = await response.json();
      if (data.pairs_count !== undefined) {
        setStats(data);
      }
    } catch (error) {
      console.error('Ошибка загрузки статистики:', error);
    }
  };

  const toggleGroupExpansion = async (groupId: number) => {
    const newExpanded = new Set(expandedGroups);
    
    if (newExpanded.has(groupId)) {
      newExpanded.delete(groupId);
    } else {
      newExpanded.add(groupId);
      
      // Загружаем детали группы, если их еще нет
      if (!groupDetails.has(groupId)) {
        try {
          const response = await fetch(`/api/alerts/${groupId}/details`);
          const data = await response.json();
          setGroupDetails(prev => {
            const newMap = new Map(prev);
            newMap.set(groupId, data.alerts || []);
            return newMap;
          });
        } catch (error) {
          console.error('Ошибка загрузки деталей группы:', error);
        }
      }
    }
    
    setExpandedGroups(newExpanded);
  };

  const deleteAlertGroup = async (groupId: number) => {
    if (confirm('Удалить эту группу алертов?')) {
      try {
        await fetch(`/api/alerts/${groupId}`, { method: 'DELETE' });
      } catch (error) {
        console.error('Ошибка удаления группы алертов:', error);
      }
    }
  };

  const clearAllAlerts = async () => {
    if (confirm('Очистить все алерты?')) {
      try {
        await fetch('/api/alerts', { method: 'DELETE' });
      } catch (error) {
        console.error('Ошибка очистки алертов:', error);
      }
    }
  };

  const addToWatchlist = async () => {
    if (!newPairSymbol.trim()) return;

    try {
      const response = await fetch('/api/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: newPairSymbol.toUpperCase() })
      });

      if (response.ok) {
        setNewPairSymbol('');
        setShowAddPair(false);
      } else {
        alert('Ошибка добавления пары');
      }
    } catch (error) {
      console.error('Ошибка добавления пары:', error);
      alert('Ошибка добавления пары');
    }
  };

  const updateWatchlistItem = async (item: WatchlistItem) => {
    try {
      const response = await fetch(`/api/watchlist/${item.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(item)
      });

      if (response.ok) {
        setEditingItem(null);
      } else {
        alert('Ошибка обновления элемента');
      }
    } catch (error) {
      console.error('Ошибка обновления элемента:', error);
      alert('Ошибка обновления элемента');
    }
  };

  const deleteWatchlistItem = async (itemId: number) => {
    if (confirm('Удалить эту пару из списка наблюдения?')) {
      try {
        await fetch(`/api/watchlist/${itemId}`, { method: 'DELETE' });
      } catch (error) {
        console.error('Ошибка удаления элемента:', error);
        alert('Ошибка удаления элемента');
      }
    }
  };

  const saveSettings = async () => {
    try {
      const response = await fetch('/api/settings', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(settings)
      });

      if (response.ok) {
        setShowSettings(false);
        alert('Настройки сохранены!');
      }
    } catch (error) {
      console.error('Ошибка сохранения настроек:', error);
      alert('Ошибка сохранения настроек');
    }
  };

  const formatPrice = (price: number) => {
    return price.toLocaleString('ru-RU', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 8
    });
  };

  const formatVolume = (volume: number) => {
    if (volume >= 1000000) {
      return `${(volume / 1000000).toFixed(1)}M`;
    } else if (volume >= 1000) {
      return `${(volume / 1000).toFixed(1)}K`;
    }
    return volume.toFixed(0);
  };

  const formatTime = (timestamp: string) => {
    try {
      return new Date(timestamp).toLocaleTimeString('ru-RU');
    } catch (error) {
      return 'Неверное время';
    }
  };

  const formatDate = (timestamp: string) => {
    try {
      return new Date(timestamp).toLocaleString('ru-RU');
    } catch (error) {
      return 'Неверная дата';
    }
  };

  const formatDuration = (startTime: string, endTime: string) => {
    try {
      const start = new Date(startTime);
      const end = new Date(endTime);
      const diffMs = end.getTime() - start.getTime();
      const diffMinutes = Math.floor(diffMs / (1000 * 60));

      if (diffMinutes < 1) {
        return 'менее минуты';
      } else if (diffMinutes < 60) {
        return `${diffMinutes} мин`;
      } else {
        const hours = Math.floor(diffMinutes / 60);
        const minutes = diffMinutes % 60;
        return `${hours}ч ${minutes}м`;
      }
    } catch (error) {
      return 'неизвестно';
    }
  };

  const liveDataArray = Array.from(liveData.values())
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    .slice(0, 50);

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-blue-900 to-gray-900 text-white">
      {/* Header */}
      <header className="bg-black bg-opacity-30 backdrop-blur-md border-b border-gray-700">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <div className="w-12 h-12 bg-gradient-to-r from-blue-500 to-purple-600 rounded-xl flex items-center justify-center">
                <BarChart3 className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent">
                  Анализатор Объемов
                </h1>
                <p className="text-gray-400 text-sm">Мониторинг торговых пар Bybit</p>
              </div>
            </div>
            <div className="flex items-center space-x-4">
              <div className="flex items-center space-x-2">
                {isConnected ? (
                  <Wifi className="w-5 h-5 text-green-400" />
                ) : (
                  <WifiOff className="w-5 h-5 text-red-400" />
                )}
                <span className="text-sm">
                  {isConnected ? 'Подключено' : 'Отключено'}
                </span>
              </div>
              {settings.telegram.enabled && (
                <div className="flex items-center space-x-2 text-green-400">
                  <span className="text-sm">📱 Telegram</span>
                </div>
              )}
              <button
                onClick={() => setShowSettings(true)}
                className="bg-white bg-opacity-10 hover:bg-opacity-20 px-4 py-2 rounded-lg transition-all flex items-center space-x-2"
              >
                <Settings className="w-4 h-4" />
                <span>Настройки</span>
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Stats Cards */}
      <div className="container mx-auto px-6 py-8">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
          <div className="bg-black bg-opacity-30 backdrop-blur-md rounded-xl p-6 border border-gray-700">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-gray-400 text-sm">Всего свечей</p>
                <p className="text-2xl font-bold text-white">{stats.total_candles}</p>
              </div>
              <Activity className="w-8 h-8 text-blue-400" />
            </div>
          </div>

          <div className="bg-black bg-opacity-30 backdrop-blur-md rounded-xl p-6 border border-gray-700">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-gray-400 text-sm">LONG свечей</p>
                <p className="text-2xl font-bold text-green-400">{stats.long_candles}</p>
              </div>
              <TrendingUp className="w-8 h-8 text-green-400" />
            </div>
          </div>

          <div className="bg-black bg-opacity-30 backdrop-blur-md rounded-xl p-6 border border-gray-700">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-gray-400 text-sm">Алертов</p>
                <p className="text-2xl font-bold text-yellow-400">{stats.alerts_count}</p>
              </div>
              <AlertTriangle className="w-8 h-8 text-yellow-400" />
            </div>
          </div>

          <div className="bg-black bg-opacity-30 backdrop-blur-md rounded-xl p-6 border border-gray-700">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-gray-400 text-sm">Торговых пар</p>
                <p className="text-2xl font-bold text-purple-400">{stats.pairs_count}</p>
              </div>
              <BarChart3 className="w-8 h-8 text-purple-400" />
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="bg-black bg-opacity-30 backdrop-blur-md rounded-xl border border-gray-700">
          <div className="flex border-b border-gray-700">
            <button
              onClick={() => setActiveTab('live')}
              className={`px-6 py-4 font-medium transition-colors ${
                activeTab === 'live'
                  ? 'text-blue-400 border-b-2 border-blue-400'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              Данные в реальном времени
            </button>
            <button
              onClick={() => setActiveTab('watchlist')}
              className={`px-6 py-4 font-medium transition-colors ${
                activeTab === 'watchlist'
                  ? 'text-blue-400 border-b-2 border-blue-400'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              Список наблюдения ({watchlist.length})
            </button>
            <button
              onClick={() => setActiveTab('alerts')}
              className={`px-6 py-4 font-medium transition-colors ${
                activeTab === 'alerts'
                  ? 'text-blue-400 border-b-2 border-blue-400'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              Алерты ({alertGroups.length})
            </button>
          </div>

          <div className="p-6">
            {activeTab === 'live' && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-700">
                      <th className="text-left py-3 px-4">Пара</th>
                      <th className="text-left py-3 px-4">Цена</th>
                      <th className="text-left py-3 px-4">Объем (USDT)</th>
                      <th className="text-left py-3 px-4">Тип</th>
                      <th className="text-left py-3 px-4">Время</th>
                      <th className="text-left py-3 px-4">Статус</th>
                    </tr>
                  </thead>
                  <tbody>
                    {liveDataArray.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="text-center py-8 text-gray-400">
                          Ожидание данных...
                        </td>
                      </tr>
                    ) : (
                      liveDataArray.map((item, index) => {
                        const isLong = parseFloat(item.data.close) > parseFloat(item.data.open);
                        const volumeUsdt = parseFloat(item.data.volume) * parseFloat(item.data.close);

                        return (
                          <tr key={`${item.symbol}-${index}`} className="border-b border-gray-700 hover:bg-gray-800 hover:bg-opacity-50">
                            <td className="py-3 px-4 font-medium">{item.symbol}</td>
                            <td className="py-3 px-4">${formatPrice(parseFloat(item.data.close))}</td>
                            <td className="py-3 px-4">${formatVolume(volumeUsdt)}</td>
                            <td className="py-3 px-4">
                              <span className={`px-2 py-1 rounded text-xs ${
                                isLong ? 'bg-green-500 bg-opacity-20 text-green-400' : 'bg-red-500 bg-opacity-20 text-red-400'
                              }`}>
                                {isLong ? 'LONG' : 'SHORT'}
                              </span>
                            </td>
                            <td className="py-3 px-4 text-gray-400">{formatTime(item.timestamp)}</td>
                            <td className="py-3 px-4">
                              {item.alert ? (
                                <span className="text-yellow-400 flex items-center space-x-1">
                                  <AlertTriangle className="w-4 h-4" />
                                  <span>
                                    Алерт {item.alert.is_grouped && `(${item.alert.group_count})`}
                                  </span>
                                </span>
                              ) : (
                                <span className="text-green-400">✓ OK</span>
                              )}
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {activeTab === 'watchlist' && (
              <div className="space-y-4">
                <div className="flex justify-between items-center">
                  <h3 className="text-lg font-semibold">Список наблюдения</h3>
                  <button
                    onClick={() => setShowAddPair(true)}
                    className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition-colors flex items-center space-x-2"
                  >
                    <Plus className="w-4 h-4" />
                    <span>Добавить пару</span>
                  </button>
                </div>

                {watchlist.length === 0 ? (
                  <div className="text-center py-8 text-gray-400">
                    Список наблюдения пуст. Ожидание обновления...
                  </div>
                ) : (
                  watchlist.map((item) => (
                    <div key={item.id} className="bg-gray-800 bg-opacity-50 rounded-lg p-4">
                      {editingItem?.id === item.id ? (
                        <div className="space-y-4">
                          <div className="grid grid-cols-2 gap-4">
                            <div>
                              <label className="block text-sm font-medium mb-2">Символ</label>
                              <input
                                type="text"
                                value={editingItem.symbol}
                                onChange={(e) => setEditingItem({...editingItem, symbol: e.target.value})}
                                className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                              />
                            </div>
                            <div className="flex items-center space-x-2">
                              <input
                                type="checkbox"
                                checked={editingItem.is_active}
                                onChange={(e) => setEditingItem({...editingItem, is_active: e.target.checked})}
                                className="w-4 h-4"
                              />
                              <label className="text-sm">Активна</label>
                            </div>
                          </div>
                          <div className="flex space-x-2">
                            <button
                              onClick={() => updateWatchlistItem(editingItem)}
                              className="bg-green-600 hover:bg-green-700 px-4 py-2 rounded-lg transition-colors"
                            >
                              Сохранить
                            </button>
                            <button
                              onClick={() => setEditingItem(null)}
                              className="bg-gray-600 hover:bg-gray-700 px-4 py-2 rounded-lg transition-colors"
                            >
                              Отмена
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-center justify-between">
                          <div className="flex items-center space-x-4">
                            <div className={`w-3 h-3 rounded-full ${
                              item.is_active ? 'bg-green-400' : 'bg-gray-400'
                            }`}></div>
                            <div>
                              <h4 className="font-bold text-lg">{item.symbol}</h4>
                              <p className="text-sm text-gray-400">
                                Падение цены: {item.price_drop_percentage?.toFixed(2)}%
                              </p>
                            </div>
                          </div>
                          <div className="flex items-center space-x-4">
                            <div className="text-right">
                              <p className="text-sm">
                                Текущая: ${formatPrice(item.current_price)}
                              </p>
                              <p className="text-sm text-gray-400">
                                Месяц назад: ${formatPrice(item.historical_price)}
                              </p>
                              <p className="text-xs text-gray-500">
                                Обновлено: {formatDate(item.updated_at)}
                              </p>
                            </div>
                            <div className="flex space-x-2">
                              <button
                                onClick={() => setEditingItem(item)}
                                className="p-2 text-blue-400 hover:bg-blue-400 hover:bg-opacity-20 rounded-lg transition-colors"
                              >
                                <Edit className="w-4 h-4" />
                              </button>
                              <button
                                onClick={() => deleteWatchlistItem(item.id)}
                                className="p-2 text-red-400 hover:bg-red-400 hover:bg-opacity-20 rounded-lg transition-colors"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            )}

            {activeTab === 'alerts' && (
              <div className="space-y-4">
                <div className="flex justify-between items-center">
                  <h3 className="text-lg font-semibold">Группы алертов</h3>
                  <button
                    onClick={clearAllAlerts}
                    className="bg-red-600 hover:bg-red-700 px-4 py-2 rounded-lg transition-colors flex items-center space-x-2"
                  >
                    <Trash2 className="w-4 h-4" />
                    <span>Очистить все</span>
                  </button>
                </div>

                {alertGroups.length === 0 ? (
                  <div className="text-center py-8 text-gray-400">
                    Алертов пока нет. Ожидание превышения объемов...
                  </div>
                ) : (
                  alertGroups.map((group) => (
                    <div key={group.id} className="bg-yellow-500 bg-opacity-10 border border-yellow-500 border-opacity-30 rounded-lg">
                      <div className="p-4">
                        <div className="flex items-center justify-between mb-3">
                          <div className="flex items-center space-x-3">
                            <button
                              onClick={() => toggleGroupExpansion(group.id)}
                              className="text-yellow-400 hover:text-yellow-300 transition-colors"
                            >
                              {expandedGroups.has(group.id) ? (
                                <ChevronDown className="w-6 h-6" />
                              ) : (
                                <ChevronRight className="w-6 h-6" />
                              )}
                            </button>
                            <AlertTriangle className="w-8 h-8 text-yellow-400" />
                            <div>
                              <div className="flex items-center space-x-2">
                                <h4 className="font-bold text-yellow-400">{group.symbol}</h4>
                                {group.alert_count > 1 && (
                                  <span className="bg-red-500 text-white text-xs px-2 py-1 rounded-full">
                                    {group.alert_count}
                                  </span>
                                )}
                              </div>
                              <p className="text-sm text-gray-300">
                                Макс. объем превышен в <strong>{group.max_volume_ratio}x</strong> раз
                              </p>
                            </div>
                          </div>
                          <div className="flex items-center space-x-4">
                            <div className="text-right">
                              <p className="text-sm text-gray-300">${formatPrice(group.max_price)}</p>
                              <p className="text-xs text-gray-400">
                                Последний: {formatDate(group.last_alert_time)}
                              </p>
                            </div>
                            <button
                              onClick={() => deleteAlertGroup(group.id)}
                              className="p-2 text-red-400 hover:bg-red-400 hover:bg-opacity-20 rounded-lg transition-colors"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4 text-sm mb-3">
                          <div>
                            <span className="text-gray-400">Макс. объем:</span>
                            <span className="text-white ml-1">${formatVolume(group.max_volume_usdt)}</span>
                          </div>
                          <div>
                            <span className="text-gray-400">Продолжительность:</span>
                            <span className="text-white ml-1">
                              {formatDuration(group.first_alert_time, group.last_alert_time)}
                            </span>
                          </div>
                        </div>
                      </div>

                      {expandedGroups.has(group.id) && (
                        <div className="border-t border-yellow-500 border-opacity-30 p-4">
                          <h5 className="text-sm font-medium text-yellow-400 mb-3">
                            История алертов ({group.alert_count})
                          </h5>
                          <div className="space-y-2 max-h-60 overflow-y-auto">
                            {groupDetails.get(group.id)?.map((alert, index) => (
                              <div key={alert.id} className="bg-black bg-opacity-20 rounded-lg p-3 text-sm">
                                <div className="flex justify-between items-start">
                                  <div>
                                    <p className="text-white">
                                      Объем: <strong>{alert.volume_ratio}x</strong> 
                                      (${formatVolume(alert.current_volume_usdt)})
                                    </p>
                                    <p className="text-gray-400">
                                      Цена: ${formatPrice(alert.price)}
                                    </p>
                                  </div>
                                  <div className="text-right">
                                    <p className="text-xs text-gray-400">
                                      {formatDate(alert.created_at)}
                                    </p>
                                    {alert.telegram_sent && (
                                      <span className="text-xs text-green-400">📱 Отправлено</span>
                                    )}
                                  </div>
                                </div>
                              </div>
                            )) || (
                              <div className="text-center text-gray-400 py-4">
                                Загрузка деталей...
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Add Pair Modal */}
      {showAddPair && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-xl p-6 max-w-md w-full mx-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold">Добавить торговую пару</h3>
              <button
                onClick={() => setShowAddPair(false)}
                className="text-gray-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">Символ (например, BTCUSDT)</label>
                <input
                  type="text"
                  value={newPairSymbol}
                  onChange={(e) => setNewPairSymbol(e.target.value)}
                  placeholder="BTCUSDT"
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                  onKeyPress={(e) => e.key === 'Enter' && addToWatchlist()}
                />
              </div>
              <div className="flex space-x-3">
                <button
                  onClick={addToWatchlist}
                  className="flex-1 bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition-colors"
                >
                  Добавить
                </button>
                <button
                  onClick={() => setShowAddPair(false)}
                  className="flex-1 bg-gray-600 hover:bg-gray-700 px-4 py-2 rounded-lg transition-colors"
                >
                  Отмена
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Settings Modal */}
      {showSettings && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-xl p-8 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-xl font-bold">Настройки анализатора</h3>
              <button
                onClick={() => setShowSettings(false)}
                className="text-gray-400 hover:text-white"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            <div className="space-y-6">
              <div>
                <h4 className="text-lg font-semibold mb-4 text-blue-400">Анализатор объемов</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-2">Период анализа (часы)</label>
                    <input
                      type="number"
                      min="1"
                      max="24"
                      value={settings.volume_analyzer.analysis_hours}
                      onChange={(e) => setSettings(prev => ({
                        ...prev,
                        volume_analyzer: {
                          ...prev.volume_analyzer,
                          analysis_hours: parseInt(e.target.value)
                        }
                      }))}
                      className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium mb-2">Смещение (минуты)</label>
                    <input
                      type="number"
                      min="0"
                      max="1440"
                      value={settings.volume_analyzer.offset_minutes}
                      onChange={(e) => setSettings(prev => ({
                        ...prev,
                        volume_analyzer: {
                          ...prev.volume_analyzer,
                          offset_minutes: parseInt(e.target.value)
                        }
                      }))}
                      className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium mb-2">Множитель объема</label>
                    <input
                      type="number"
                      min="1"
                      max="10"
                      step="0.1"
                      value={settings.volume_analyzer.volume_multiplier}
                      onChange={(e) => setSettings(prev => ({
                        ...prev,
                        volume_analyzer: {
                          ...prev.volume_analyzer,
                          volume_multiplier: parseFloat(e.target.value)
                        }
                      }))}
                      className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium mb-2">Мин. объем (USDT)</label>
                    <input
                      type="number"
                      min="100"
                      value={settings.volume_analyzer.min_volume_usdt}
                      onChange={(e) => setSettings(prev => ({
                        ...prev,
                        volume_analyzer: {
                          ...prev.volume_analyzer,
                          min_volume_usdt: parseInt(e.target.value)
                        }
                      }))}
                      className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                    />
                  </div>

                  <div className="col-span-2">
                    <label className="block text-sm font-medium mb-2">Группировка алертов (минуты)</label>
                    <input
                      type="number"
                      min="1"
                      max="60"
                      value={settings.volume_analyzer.alert_grouping_minutes}
                      onChange={(e) => setSettings(prev => ({
                        ...prev,
                        volume_analyzer: {
                          ...prev.volume_analyzer,
                          alert_grouping_minutes: parseInt(e.target.value)
                        }
                      }))}
                      className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                    />
                    <p className="text-xs text-gray-400 mt-1">
                      Алерты для одного актива в течение этого времени будут группироваться
                    </p>
                  </div>
                </div>
              </div>

              <div>
                <h4 className="text-lg font-semibold mb-4 text-purple-400">Фильтр по цене</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-2">Интервал проверки (мин)</label>
                    <input
                      type="number"
                      min="1"
                      max="60"
                      value={settings.price_filter.price_check_interval_minutes}
                      onChange={(e) => setSettings(prev => ({
                        ...prev,
                        price_filter: {
                          ...prev.price_filter,
                          price_check_interval_minutes: parseInt(e.target.value)
                        }
                      }))}
                      className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                    />
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium mb-2">Период истории (дни)</label>
                    <input
                      type="number"
                      min="1"
                      max="365"
                      value={settings.price_filter.price_history_days}
                      onChange={(e) => setSettings(prev => ({
                        ...prev,
                        price_filter: {
                          ...prev.price_filter,
                          price_history_days: parseInt(e.target.value)
                        }
                      }))}
                      className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                    />
                  </div>
                  
                  <div className="col-span-2">
                    <label className="block text-sm font-medium mb-2">Падение цены (%)</label>
                    <input
                      type="number"
                      min="1"
                      max="90"
                      step="0.1"
                      value={settings.price_filter.price_drop_percentage}
                      onChange={(e) => setSettings(prev => ({
                        ...prev,
                        price_filter: {
                          ...prev.price_filter,
                          price_drop_percentage: parseFloat(e.target.value)
                        }
                      }))}
                      className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                    />
                  </div>
                </div>
              </div>

              <div>
                <h4 className="text-lg font-semibold mb-4 text-green-400">Telegram уведомления</h4>
                <div className="bg-gray-700 rounded-lg p-4">
                  <div className="flex items-center space-x-2 mb-3">
                    <span className={`w-3 h-3 rounded-full ${settings.telegram.enabled ? 'bg-green-400' : 'bg-red-400'}`}></span>
                    <span className="text-sm">
                      {settings.telegram.enabled ? 'Подключено' : 'Не настроено'}
                    </span>
                  </div>
                  <p className="text-xs text-gray-400">
                    Для настройки Telegram уведомлений добавьте в .env файл:
                  </p>
                  <div className="bg-black bg-opacity-50 rounded p-2 mt-2 text-xs font-mono">
                    TELEGRAM_BOT_TOKEN=your_bot_token<br/>
                    TELEGRAM_CHAT_ID=your_chat_id
                  </div>
                </div>
              </div>
            </div>
            
            <div className="flex space-x-3 mt-8">
              <button
                onClick={saveSettings}
                className="flex-1 bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition-colors"
              >
                Сохранить
              </button>
              <button
                onClick={() => setShowSettings(false)}
                className="flex-1 bg-gray-600 hover:bg-gray-700 px-4 py-2 rounded-lg transition-colors"
              >
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;