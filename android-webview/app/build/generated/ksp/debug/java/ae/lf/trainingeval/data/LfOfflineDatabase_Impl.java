package ae.lf.trainingeval.data;

import androidx.annotation.NonNull;
import androidx.room.DatabaseConfiguration;
import androidx.room.InvalidationTracker;
import androidx.room.RoomDatabase;
import androidx.room.RoomOpenHelper;
import androidx.room.migration.AutoMigrationSpec;
import androidx.room.migration.Migration;
import androidx.room.util.DBUtil;
import androidx.room.util.TableInfo;
import androidx.sqlite.db.SupportSQLiteDatabase;
import androidx.sqlite.db.SupportSQLiteOpenHelper;
import java.lang.Class;
import java.lang.Override;
import java.lang.String;
import java.lang.SuppressWarnings;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import javax.annotation.processing.Generated;

@Generated("androidx.room.RoomProcessor")
@SuppressWarnings({"unchecked", "deprecation"})
public final class LfOfflineDatabase_Impl extends LfOfflineDatabase {
  private volatile OfflineOperationDao _offlineOperationDao;

  private volatile CachedPageDao _cachedPageDao;

  @Override
  @NonNull
  protected SupportSQLiteOpenHelper createOpenHelper(@NonNull final DatabaseConfiguration config) {
    final SupportSQLiteOpenHelper.Callback _openCallback = new RoomOpenHelper(config, new RoomOpenHelper.Delegate(2) {
      @Override
      public void createAllTables(@NonNull final SupportSQLiteDatabase db) {
        db.execSQL("CREATE TABLE IF NOT EXISTS `offline_operations` (`clientOperationId` TEXT NOT NULL, `type` TEXT NOT NULL, `url` TEXT NOT NULL, `payloadJson` TEXT, `fileBase64` TEXT, `evaluationListItemId` TEXT, `itemId` TEXT, `rowIndex` TEXT, `mediaKind` TEXT, `bundleActionEvalId` TEXT, `exerciseId` TEXT, `unitLevelKey` TEXT, `mimeType` TEXT, `createdAt` INTEGER NOT NULL, `status` TEXT NOT NULL, PRIMARY KEY(`clientOperationId`))");
        db.execSQL("CREATE TABLE IF NOT EXISTS `cached_pages` (`urlKey` TEXT NOT NULL, `url` TEXT NOT NULL, `mimeType` TEXT NOT NULL, `encoding` TEXT NOT NULL, `statusCode` INTEGER NOT NULL, `bodyFile` TEXT NOT NULL, `bodySize` INTEGER NOT NULL, `cachedAt` INTEGER NOT NULL, PRIMARY KEY(`urlKey`))");
        db.execSQL("CREATE TABLE IF NOT EXISTS room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)");
        db.execSQL("INSERT OR REPLACE INTO room_master_table (id,identity_hash) VALUES(42, 'cfe80eac273851d7357f0c0d67759774')");
      }

      @Override
      public void dropAllTables(@NonNull final SupportSQLiteDatabase db) {
        db.execSQL("DROP TABLE IF EXISTS `offline_operations`");
        db.execSQL("DROP TABLE IF EXISTS `cached_pages`");
        final List<? extends RoomDatabase.Callback> _callbacks = mCallbacks;
        if (_callbacks != null) {
          for (RoomDatabase.Callback _callback : _callbacks) {
            _callback.onDestructiveMigration(db);
          }
        }
      }

      @Override
      public void onCreate(@NonNull final SupportSQLiteDatabase db) {
        final List<? extends RoomDatabase.Callback> _callbacks = mCallbacks;
        if (_callbacks != null) {
          for (RoomDatabase.Callback _callback : _callbacks) {
            _callback.onCreate(db);
          }
        }
      }

      @Override
      public void onOpen(@NonNull final SupportSQLiteDatabase db) {
        mDatabase = db;
        internalInitInvalidationTracker(db);
        final List<? extends RoomDatabase.Callback> _callbacks = mCallbacks;
        if (_callbacks != null) {
          for (RoomDatabase.Callback _callback : _callbacks) {
            _callback.onOpen(db);
          }
        }
      }

      @Override
      public void onPreMigrate(@NonNull final SupportSQLiteDatabase db) {
        DBUtil.dropFtsSyncTriggers(db);
      }

      @Override
      public void onPostMigrate(@NonNull final SupportSQLiteDatabase db) {
      }

      @Override
      @NonNull
      public RoomOpenHelper.ValidationResult onValidateSchema(
          @NonNull final SupportSQLiteDatabase db) {
        final HashMap<String, TableInfo.Column> _columnsOfflineOperations = new HashMap<String, TableInfo.Column>(15);
        _columnsOfflineOperations.put("clientOperationId", new TableInfo.Column("clientOperationId", "TEXT", true, 1, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("type", new TableInfo.Column("type", "TEXT", true, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("url", new TableInfo.Column("url", "TEXT", true, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("payloadJson", new TableInfo.Column("payloadJson", "TEXT", false, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("fileBase64", new TableInfo.Column("fileBase64", "TEXT", false, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("evaluationListItemId", new TableInfo.Column("evaluationListItemId", "TEXT", false, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("itemId", new TableInfo.Column("itemId", "TEXT", false, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("rowIndex", new TableInfo.Column("rowIndex", "TEXT", false, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("mediaKind", new TableInfo.Column("mediaKind", "TEXT", false, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("bundleActionEvalId", new TableInfo.Column("bundleActionEvalId", "TEXT", false, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("exerciseId", new TableInfo.Column("exerciseId", "TEXT", false, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("unitLevelKey", new TableInfo.Column("unitLevelKey", "TEXT", false, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("mimeType", new TableInfo.Column("mimeType", "TEXT", false, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("createdAt", new TableInfo.Column("createdAt", "INTEGER", true, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsOfflineOperations.put("status", new TableInfo.Column("status", "TEXT", true, 0, null, TableInfo.CREATED_FROM_ENTITY));
        final HashSet<TableInfo.ForeignKey> _foreignKeysOfflineOperations = new HashSet<TableInfo.ForeignKey>(0);
        final HashSet<TableInfo.Index> _indicesOfflineOperations = new HashSet<TableInfo.Index>(0);
        final TableInfo _infoOfflineOperations = new TableInfo("offline_operations", _columnsOfflineOperations, _foreignKeysOfflineOperations, _indicesOfflineOperations);
        final TableInfo _existingOfflineOperations = TableInfo.read(db, "offline_operations");
        if (!_infoOfflineOperations.equals(_existingOfflineOperations)) {
          return new RoomOpenHelper.ValidationResult(false, "offline_operations(ae.lf.trainingeval.data.OfflineOperationEntity).\n"
                  + " Expected:\n" + _infoOfflineOperations + "\n"
                  + " Found:\n" + _existingOfflineOperations);
        }
        final HashMap<String, TableInfo.Column> _columnsCachedPages = new HashMap<String, TableInfo.Column>(8);
        _columnsCachedPages.put("urlKey", new TableInfo.Column("urlKey", "TEXT", true, 1, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsCachedPages.put("url", new TableInfo.Column("url", "TEXT", true, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsCachedPages.put("mimeType", new TableInfo.Column("mimeType", "TEXT", true, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsCachedPages.put("encoding", new TableInfo.Column("encoding", "TEXT", true, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsCachedPages.put("statusCode", new TableInfo.Column("statusCode", "INTEGER", true, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsCachedPages.put("bodyFile", new TableInfo.Column("bodyFile", "TEXT", true, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsCachedPages.put("bodySize", new TableInfo.Column("bodySize", "INTEGER", true, 0, null, TableInfo.CREATED_FROM_ENTITY));
        _columnsCachedPages.put("cachedAt", new TableInfo.Column("cachedAt", "INTEGER", true, 0, null, TableInfo.CREATED_FROM_ENTITY));
        final HashSet<TableInfo.ForeignKey> _foreignKeysCachedPages = new HashSet<TableInfo.ForeignKey>(0);
        final HashSet<TableInfo.Index> _indicesCachedPages = new HashSet<TableInfo.Index>(0);
        final TableInfo _infoCachedPages = new TableInfo("cached_pages", _columnsCachedPages, _foreignKeysCachedPages, _indicesCachedPages);
        final TableInfo _existingCachedPages = TableInfo.read(db, "cached_pages");
        if (!_infoCachedPages.equals(_existingCachedPages)) {
          return new RoomOpenHelper.ValidationResult(false, "cached_pages(ae.lf.trainingeval.data.CachedPageEntity).\n"
                  + " Expected:\n" + _infoCachedPages + "\n"
                  + " Found:\n" + _existingCachedPages);
        }
        return new RoomOpenHelper.ValidationResult(true, null);
      }
    }, "cfe80eac273851d7357f0c0d67759774", "a545280e3bf8e57fcc0fec4c52ffb12e");
    final SupportSQLiteOpenHelper.Configuration _sqliteConfig = SupportSQLiteOpenHelper.Configuration.builder(config.context).name(config.name).callback(_openCallback).build();
    final SupportSQLiteOpenHelper _helper = config.sqliteOpenHelperFactory.create(_sqliteConfig);
    return _helper;
  }

  @Override
  @NonNull
  protected InvalidationTracker createInvalidationTracker() {
    final HashMap<String, String> _shadowTablesMap = new HashMap<String, String>(0);
    final HashMap<String, Set<String>> _viewTables = new HashMap<String, Set<String>>(0);
    return new InvalidationTracker(this, _shadowTablesMap, _viewTables, "offline_operations","cached_pages");
  }

  @Override
  public void clearAllTables() {
    super.assertNotMainThread();
    final SupportSQLiteDatabase _db = super.getOpenHelper().getWritableDatabase();
    try {
      super.beginTransaction();
      _db.execSQL("DELETE FROM `offline_operations`");
      _db.execSQL("DELETE FROM `cached_pages`");
      super.setTransactionSuccessful();
    } finally {
      super.endTransaction();
      _db.query("PRAGMA wal_checkpoint(FULL)").close();
      if (!_db.inTransaction()) {
        _db.execSQL("VACUUM");
      }
    }
  }

  @Override
  @NonNull
  protected Map<Class<?>, List<Class<?>>> getRequiredTypeConverters() {
    final HashMap<Class<?>, List<Class<?>>> _typeConvertersMap = new HashMap<Class<?>, List<Class<?>>>();
    _typeConvertersMap.put(OfflineOperationDao.class, OfflineOperationDao_Impl.getRequiredConverters());
    _typeConvertersMap.put(CachedPageDao.class, CachedPageDao_Impl.getRequiredConverters());
    return _typeConvertersMap;
  }

  @Override
  @NonNull
  public Set<Class<? extends AutoMigrationSpec>> getRequiredAutoMigrationSpecs() {
    final HashSet<Class<? extends AutoMigrationSpec>> _autoMigrationSpecsSet = new HashSet<Class<? extends AutoMigrationSpec>>();
    return _autoMigrationSpecsSet;
  }

  @Override
  @NonNull
  public List<Migration> getAutoMigrations(
      @NonNull final Map<Class<? extends AutoMigrationSpec>, AutoMigrationSpec> autoMigrationSpecs) {
    final List<Migration> _autoMigrations = new ArrayList<Migration>();
    return _autoMigrations;
  }

  @Override
  public OfflineOperationDao offlineOperationDao() {
    if (_offlineOperationDao != null) {
      return _offlineOperationDao;
    } else {
      synchronized(this) {
        if(_offlineOperationDao == null) {
          _offlineOperationDao = new OfflineOperationDao_Impl(this);
        }
        return _offlineOperationDao;
      }
    }
  }

  @Override
  public CachedPageDao cachedPageDao() {
    if (_cachedPageDao != null) {
      return _cachedPageDao;
    } else {
      synchronized(this) {
        if(_cachedPageDao == null) {
          _cachedPageDao = new CachedPageDao_Impl(this);
        }
        return _cachedPageDao;
      }
    }
  }
}
