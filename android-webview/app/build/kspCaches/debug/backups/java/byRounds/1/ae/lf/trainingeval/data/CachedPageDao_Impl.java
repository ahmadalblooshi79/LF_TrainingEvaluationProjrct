package ae.lf.trainingeval.data;

import android.database.Cursor;
import android.os.CancellationSignal;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.room.CoroutinesRoom;
import androidx.room.EntityInsertionAdapter;
import androidx.room.RoomDatabase;
import androidx.room.RoomSQLiteQuery;
import androidx.room.SharedSQLiteStatement;
import androidx.room.util.CursorUtil;
import androidx.room.util.DBUtil;
import androidx.sqlite.db.SupportSQLiteStatement;
import java.lang.Class;
import java.lang.Exception;
import java.lang.Integer;
import java.lang.Object;
import java.lang.Override;
import java.lang.String;
import java.lang.SuppressWarnings;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.Callable;
import javax.annotation.processing.Generated;
import kotlin.Unit;
import kotlin.coroutines.Continuation;

@Generated("androidx.room.RoomProcessor")
@SuppressWarnings({"unchecked", "deprecation"})
public final class CachedPageDao_Impl implements CachedPageDao {
  private final RoomDatabase __db;

  private final EntityInsertionAdapter<CachedPageEntity> __insertionAdapterOfCachedPageEntity;

  private final SharedSQLiteStatement __preparedStmtOfDeleteByKey;

  public CachedPageDao_Impl(@NonNull final RoomDatabase __db) {
    this.__db = __db;
    this.__insertionAdapterOfCachedPageEntity = new EntityInsertionAdapter<CachedPageEntity>(__db) {
      @Override
      @NonNull
      protected String createQuery() {
        return "INSERT OR REPLACE INTO `cached_pages` (`urlKey`,`url`,`mimeType`,`encoding`,`statusCode`,`bodyFile`,`bodySize`,`cachedAt`) VALUES (?,?,?,?,?,?,?,?)";
      }

      @Override
      protected void bind(@NonNull final SupportSQLiteStatement statement,
          @NonNull final CachedPageEntity entity) {
        statement.bindString(1, entity.getUrlKey());
        statement.bindString(2, entity.getUrl());
        statement.bindString(3, entity.getMimeType());
        statement.bindString(4, entity.getEncoding());
        statement.bindLong(5, entity.getStatusCode());
        statement.bindString(6, entity.getBodyFile());
        statement.bindLong(7, entity.getBodySize());
        statement.bindLong(8, entity.getCachedAt());
      }
    };
    this.__preparedStmtOfDeleteByKey = new SharedSQLiteStatement(__db) {
      @Override
      @NonNull
      public String createQuery() {
        final String _query = "DELETE FROM cached_pages WHERE urlKey = ?";
        return _query;
      }
    };
  }

  @Override
  public Object upsert(final CachedPageEntity entity,
      final Continuation<? super Unit> $completion) {
    return CoroutinesRoom.execute(__db, true, new Callable<Unit>() {
      @Override
      @NonNull
      public Unit call() throws Exception {
        __db.beginTransaction();
        try {
          __insertionAdapterOfCachedPageEntity.insert(entity);
          __db.setTransactionSuccessful();
          return Unit.INSTANCE;
        } finally {
          __db.endTransaction();
        }
      }
    }, $completion);
  }

  @Override
  public Object deleteByKey(final String key, final Continuation<? super Unit> $completion) {
    return CoroutinesRoom.execute(__db, true, new Callable<Unit>() {
      @Override
      @NonNull
      public Unit call() throws Exception {
        final SupportSQLiteStatement _stmt = __preparedStmtOfDeleteByKey.acquire();
        int _argIndex = 1;
        _stmt.bindString(_argIndex, key);
        try {
          __db.beginTransaction();
          try {
            _stmt.executeUpdateDelete();
            __db.setTransactionSuccessful();
            return Unit.INSTANCE;
          } finally {
            __db.endTransaction();
          }
        } finally {
          __preparedStmtOfDeleteByKey.release(_stmt);
        }
      }
    }, $completion);
  }

  @Override
  public Object getByKey(final String key,
      final Continuation<? super CachedPageEntity> $completion) {
    final String _sql = "SELECT * FROM cached_pages WHERE urlKey = ? LIMIT 1";
    final RoomSQLiteQuery _statement = RoomSQLiteQuery.acquire(_sql, 1);
    int _argIndex = 1;
    _statement.bindString(_argIndex, key);
    final CancellationSignal _cancellationSignal = DBUtil.createCancellationSignal();
    return CoroutinesRoom.execute(__db, false, _cancellationSignal, new Callable<CachedPageEntity>() {
      @Override
      @Nullable
      public CachedPageEntity call() throws Exception {
        final Cursor _cursor = DBUtil.query(__db, _statement, false, null);
        try {
          final int _cursorIndexOfUrlKey = CursorUtil.getColumnIndexOrThrow(_cursor, "urlKey");
          final int _cursorIndexOfUrl = CursorUtil.getColumnIndexOrThrow(_cursor, "url");
          final int _cursorIndexOfMimeType = CursorUtil.getColumnIndexOrThrow(_cursor, "mimeType");
          final int _cursorIndexOfEncoding = CursorUtil.getColumnIndexOrThrow(_cursor, "encoding");
          final int _cursorIndexOfStatusCode = CursorUtil.getColumnIndexOrThrow(_cursor, "statusCode");
          final int _cursorIndexOfBodyFile = CursorUtil.getColumnIndexOrThrow(_cursor, "bodyFile");
          final int _cursorIndexOfBodySize = CursorUtil.getColumnIndexOrThrow(_cursor, "bodySize");
          final int _cursorIndexOfCachedAt = CursorUtil.getColumnIndexOrThrow(_cursor, "cachedAt");
          final CachedPageEntity _result;
          if (_cursor.moveToFirst()) {
            final String _tmpUrlKey;
            _tmpUrlKey = _cursor.getString(_cursorIndexOfUrlKey);
            final String _tmpUrl;
            _tmpUrl = _cursor.getString(_cursorIndexOfUrl);
            final String _tmpMimeType;
            _tmpMimeType = _cursor.getString(_cursorIndexOfMimeType);
            final String _tmpEncoding;
            _tmpEncoding = _cursor.getString(_cursorIndexOfEncoding);
            final int _tmpStatusCode;
            _tmpStatusCode = _cursor.getInt(_cursorIndexOfStatusCode);
            final String _tmpBodyFile;
            _tmpBodyFile = _cursor.getString(_cursorIndexOfBodyFile);
            final long _tmpBodySize;
            _tmpBodySize = _cursor.getLong(_cursorIndexOfBodySize);
            final long _tmpCachedAt;
            _tmpCachedAt = _cursor.getLong(_cursorIndexOfCachedAt);
            _result = new CachedPageEntity(_tmpUrlKey,_tmpUrl,_tmpMimeType,_tmpEncoding,_tmpStatusCode,_tmpBodyFile,_tmpBodySize,_tmpCachedAt);
          } else {
            _result = null;
          }
          return _result;
        } finally {
          _cursor.close();
          _statement.release();
        }
      }
    }, $completion);
  }

  @Override
  public Object getByUrl(final String url,
      final Continuation<? super CachedPageEntity> $completion) {
    final String _sql = "SELECT * FROM cached_pages WHERE url = ? ORDER BY cachedAt DESC LIMIT 1";
    final RoomSQLiteQuery _statement = RoomSQLiteQuery.acquire(_sql, 1);
    int _argIndex = 1;
    _statement.bindString(_argIndex, url);
    final CancellationSignal _cancellationSignal = DBUtil.createCancellationSignal();
    return CoroutinesRoom.execute(__db, false, _cancellationSignal, new Callable<CachedPageEntity>() {
      @Override
      @Nullable
      public CachedPageEntity call() throws Exception {
        final Cursor _cursor = DBUtil.query(__db, _statement, false, null);
        try {
          final int _cursorIndexOfUrlKey = CursorUtil.getColumnIndexOrThrow(_cursor, "urlKey");
          final int _cursorIndexOfUrl = CursorUtil.getColumnIndexOrThrow(_cursor, "url");
          final int _cursorIndexOfMimeType = CursorUtil.getColumnIndexOrThrow(_cursor, "mimeType");
          final int _cursorIndexOfEncoding = CursorUtil.getColumnIndexOrThrow(_cursor, "encoding");
          final int _cursorIndexOfStatusCode = CursorUtil.getColumnIndexOrThrow(_cursor, "statusCode");
          final int _cursorIndexOfBodyFile = CursorUtil.getColumnIndexOrThrow(_cursor, "bodyFile");
          final int _cursorIndexOfBodySize = CursorUtil.getColumnIndexOrThrow(_cursor, "bodySize");
          final int _cursorIndexOfCachedAt = CursorUtil.getColumnIndexOrThrow(_cursor, "cachedAt");
          final CachedPageEntity _result;
          if (_cursor.moveToFirst()) {
            final String _tmpUrlKey;
            _tmpUrlKey = _cursor.getString(_cursorIndexOfUrlKey);
            final String _tmpUrl;
            _tmpUrl = _cursor.getString(_cursorIndexOfUrl);
            final String _tmpMimeType;
            _tmpMimeType = _cursor.getString(_cursorIndexOfMimeType);
            final String _tmpEncoding;
            _tmpEncoding = _cursor.getString(_cursorIndexOfEncoding);
            final int _tmpStatusCode;
            _tmpStatusCode = _cursor.getInt(_cursorIndexOfStatusCode);
            final String _tmpBodyFile;
            _tmpBodyFile = _cursor.getString(_cursorIndexOfBodyFile);
            final long _tmpBodySize;
            _tmpBodySize = _cursor.getLong(_cursorIndexOfBodySize);
            final long _tmpCachedAt;
            _tmpCachedAt = _cursor.getLong(_cursorIndexOfCachedAt);
            _result = new CachedPageEntity(_tmpUrlKey,_tmpUrl,_tmpMimeType,_tmpEncoding,_tmpStatusCode,_tmpBodyFile,_tmpBodySize,_tmpCachedAt);
          } else {
            _result = null;
          }
          return _result;
        } finally {
          _cursor.close();
          _statement.release();
        }
      }
    }, $completion);
  }

  @Override
  public Object count(final Continuation<? super Integer> $completion) {
    final String _sql = "SELECT COUNT(*) FROM cached_pages";
    final RoomSQLiteQuery _statement = RoomSQLiteQuery.acquire(_sql, 0);
    final CancellationSignal _cancellationSignal = DBUtil.createCancellationSignal();
    return CoroutinesRoom.execute(__db, false, _cancellationSignal, new Callable<Integer>() {
      @Override
      @NonNull
      public Integer call() throws Exception {
        final Cursor _cursor = DBUtil.query(__db, _statement, false, null);
        try {
          final Integer _result;
          if (_cursor.moveToFirst()) {
            final int _tmp;
            _tmp = _cursor.getInt(0);
            _result = _tmp;
          } else {
            _result = 0;
          }
          return _result;
        } finally {
          _cursor.close();
          _statement.release();
        }
      }
    }, $completion);
  }

  @Override
  public Object oldest(final int limit,
      final Continuation<? super List<CachedPageEntity>> $completion) {
    final String _sql = "\n"
            + "        SELECT * FROM cached_pages\n"
            + "        ORDER BY cachedAt ASC\n"
            + "        LIMIT ?\n"
            + "        ";
    final RoomSQLiteQuery _statement = RoomSQLiteQuery.acquire(_sql, 1);
    int _argIndex = 1;
    _statement.bindLong(_argIndex, limit);
    final CancellationSignal _cancellationSignal = DBUtil.createCancellationSignal();
    return CoroutinesRoom.execute(__db, false, _cancellationSignal, new Callable<List<CachedPageEntity>>() {
      @Override
      @NonNull
      public List<CachedPageEntity> call() throws Exception {
        final Cursor _cursor = DBUtil.query(__db, _statement, false, null);
        try {
          final int _cursorIndexOfUrlKey = CursorUtil.getColumnIndexOrThrow(_cursor, "urlKey");
          final int _cursorIndexOfUrl = CursorUtil.getColumnIndexOrThrow(_cursor, "url");
          final int _cursorIndexOfMimeType = CursorUtil.getColumnIndexOrThrow(_cursor, "mimeType");
          final int _cursorIndexOfEncoding = CursorUtil.getColumnIndexOrThrow(_cursor, "encoding");
          final int _cursorIndexOfStatusCode = CursorUtil.getColumnIndexOrThrow(_cursor, "statusCode");
          final int _cursorIndexOfBodyFile = CursorUtil.getColumnIndexOrThrow(_cursor, "bodyFile");
          final int _cursorIndexOfBodySize = CursorUtil.getColumnIndexOrThrow(_cursor, "bodySize");
          final int _cursorIndexOfCachedAt = CursorUtil.getColumnIndexOrThrow(_cursor, "cachedAt");
          final List<CachedPageEntity> _result = new ArrayList<CachedPageEntity>(_cursor.getCount());
          while (_cursor.moveToNext()) {
            final CachedPageEntity _item;
            final String _tmpUrlKey;
            _tmpUrlKey = _cursor.getString(_cursorIndexOfUrlKey);
            final String _tmpUrl;
            _tmpUrl = _cursor.getString(_cursorIndexOfUrl);
            final String _tmpMimeType;
            _tmpMimeType = _cursor.getString(_cursorIndexOfMimeType);
            final String _tmpEncoding;
            _tmpEncoding = _cursor.getString(_cursorIndexOfEncoding);
            final int _tmpStatusCode;
            _tmpStatusCode = _cursor.getInt(_cursorIndexOfStatusCode);
            final String _tmpBodyFile;
            _tmpBodyFile = _cursor.getString(_cursorIndexOfBodyFile);
            final long _tmpBodySize;
            _tmpBodySize = _cursor.getLong(_cursorIndexOfBodySize);
            final long _tmpCachedAt;
            _tmpCachedAt = _cursor.getLong(_cursorIndexOfCachedAt);
            _item = new CachedPageEntity(_tmpUrlKey,_tmpUrl,_tmpMimeType,_tmpEncoding,_tmpStatusCode,_tmpBodyFile,_tmpBodySize,_tmpCachedAt);
            _result.add(_item);
          }
          return _result;
        } finally {
          _cursor.close();
          _statement.release();
        }
      }
    }, $completion);
  }

  @NonNull
  public static List<Class<?>> getRequiredConverters() {
    return Collections.emptyList();
  }
}
