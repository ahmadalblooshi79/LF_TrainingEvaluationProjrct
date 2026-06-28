package ae.lf.trainingeval.data;

import android.database.Cursor;
import android.os.CancellationSignal;
import androidx.annotation.NonNull;
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
public final class OfflineOperationDao_Impl implements OfflineOperationDao {
  private final RoomDatabase __db;

  private final EntityInsertionAdapter<OfflineOperationEntity> __insertionAdapterOfOfflineOperationEntity;

  private final SharedSQLiteStatement __preparedStmtOfDeleteById;

  private final SharedSQLiteStatement __preparedStmtOfUpdateStatus;

  public OfflineOperationDao_Impl(@NonNull final RoomDatabase __db) {
    this.__db = __db;
    this.__insertionAdapterOfOfflineOperationEntity = new EntityInsertionAdapter<OfflineOperationEntity>(__db) {
      @Override
      @NonNull
      protected String createQuery() {
        return "INSERT OR REPLACE INTO `offline_operations` (`clientOperationId`,`type`,`url`,`payloadJson`,`fileBase64`,`evaluationListItemId`,`itemId`,`rowIndex`,`mediaKind`,`bundleActionEvalId`,`exerciseId`,`unitLevelKey`,`mimeType`,`createdAt`,`status`) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)";
      }

      @Override
      protected void bind(@NonNull final SupportSQLiteStatement statement,
          @NonNull final OfflineOperationEntity entity) {
        statement.bindString(1, entity.getClientOperationId());
        statement.bindString(2, entity.getType());
        statement.bindString(3, entity.getUrl());
        if (entity.getPayloadJson() == null) {
          statement.bindNull(4);
        } else {
          statement.bindString(4, entity.getPayloadJson());
        }
        if (entity.getFileBase64() == null) {
          statement.bindNull(5);
        } else {
          statement.bindString(5, entity.getFileBase64());
        }
        if (entity.getEvaluationListItemId() == null) {
          statement.bindNull(6);
        } else {
          statement.bindString(6, entity.getEvaluationListItemId());
        }
        if (entity.getItemId() == null) {
          statement.bindNull(7);
        } else {
          statement.bindString(7, entity.getItemId());
        }
        if (entity.getRowIndex() == null) {
          statement.bindNull(8);
        } else {
          statement.bindString(8, entity.getRowIndex());
        }
        if (entity.getMediaKind() == null) {
          statement.bindNull(9);
        } else {
          statement.bindString(9, entity.getMediaKind());
        }
        if (entity.getBundleActionEvalId() == null) {
          statement.bindNull(10);
        } else {
          statement.bindString(10, entity.getBundleActionEvalId());
        }
        if (entity.getExerciseId() == null) {
          statement.bindNull(11);
        } else {
          statement.bindString(11, entity.getExerciseId());
        }
        if (entity.getUnitLevelKey() == null) {
          statement.bindNull(12);
        } else {
          statement.bindString(12, entity.getUnitLevelKey());
        }
        if (entity.getMimeType() == null) {
          statement.bindNull(13);
        } else {
          statement.bindString(13, entity.getMimeType());
        }
        statement.bindLong(14, entity.getCreatedAt());
        statement.bindString(15, entity.getStatus());
      }
    };
    this.__preparedStmtOfDeleteById = new SharedSQLiteStatement(__db) {
      @Override
      @NonNull
      public String createQuery() {
        final String _query = "DELETE FROM offline_operations WHERE clientOperationId = ?";
        return _query;
      }
    };
    this.__preparedStmtOfUpdateStatus = new SharedSQLiteStatement(__db) {
      @Override
      @NonNull
      public String createQuery() {
        final String _query = "UPDATE offline_operations SET status = ? WHERE clientOperationId = ?";
        return _query;
      }
    };
  }

  @Override
  public Object upsert(final OfflineOperationEntity entity,
      final Continuation<? super Unit> $completion) {
    return CoroutinesRoom.execute(__db, true, new Callable<Unit>() {
      @Override
      @NonNull
      public Unit call() throws Exception {
        __db.beginTransaction();
        try {
          __insertionAdapterOfOfflineOperationEntity.insert(entity);
          __db.setTransactionSuccessful();
          return Unit.INSTANCE;
        } finally {
          __db.endTransaction();
        }
      }
    }, $completion);
  }

  @Override
  public Object deleteById(final String id, final Continuation<? super Unit> $completion) {
    return CoroutinesRoom.execute(__db, true, new Callable<Unit>() {
      @Override
      @NonNull
      public Unit call() throws Exception {
        final SupportSQLiteStatement _stmt = __preparedStmtOfDeleteById.acquire();
        int _argIndex = 1;
        _stmt.bindString(_argIndex, id);
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
          __preparedStmtOfDeleteById.release(_stmt);
        }
      }
    }, $completion);
  }

  @Override
  public Object updateStatus(final String id, final String status,
      final Continuation<? super Unit> $completion) {
    return CoroutinesRoom.execute(__db, true, new Callable<Unit>() {
      @Override
      @NonNull
      public Unit call() throws Exception {
        final SupportSQLiteStatement _stmt = __preparedStmtOfUpdateStatus.acquire();
        int _argIndex = 1;
        _stmt.bindString(_argIndex, status);
        _argIndex = 2;
        _stmt.bindString(_argIndex, id);
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
          __preparedStmtOfUpdateStatus.release(_stmt);
        }
      }
    }, $completion);
  }

  @Override
  public Object getPending(final Continuation<? super List<OfflineOperationEntity>> $completion) {
    final String _sql = "SELECT * FROM offline_operations WHERE status IN ('pending', 'failed') ORDER BY createdAt ASC";
    final RoomSQLiteQuery _statement = RoomSQLiteQuery.acquire(_sql, 0);
    final CancellationSignal _cancellationSignal = DBUtil.createCancellationSignal();
    return CoroutinesRoom.execute(__db, false, _cancellationSignal, new Callable<List<OfflineOperationEntity>>() {
      @Override
      @NonNull
      public List<OfflineOperationEntity> call() throws Exception {
        final Cursor _cursor = DBUtil.query(__db, _statement, false, null);
        try {
          final int _cursorIndexOfClientOperationId = CursorUtil.getColumnIndexOrThrow(_cursor, "clientOperationId");
          final int _cursorIndexOfType = CursorUtil.getColumnIndexOrThrow(_cursor, "type");
          final int _cursorIndexOfUrl = CursorUtil.getColumnIndexOrThrow(_cursor, "url");
          final int _cursorIndexOfPayloadJson = CursorUtil.getColumnIndexOrThrow(_cursor, "payloadJson");
          final int _cursorIndexOfFileBase64 = CursorUtil.getColumnIndexOrThrow(_cursor, "fileBase64");
          final int _cursorIndexOfEvaluationListItemId = CursorUtil.getColumnIndexOrThrow(_cursor, "evaluationListItemId");
          final int _cursorIndexOfItemId = CursorUtil.getColumnIndexOrThrow(_cursor, "itemId");
          final int _cursorIndexOfRowIndex = CursorUtil.getColumnIndexOrThrow(_cursor, "rowIndex");
          final int _cursorIndexOfMediaKind = CursorUtil.getColumnIndexOrThrow(_cursor, "mediaKind");
          final int _cursorIndexOfBundleActionEvalId = CursorUtil.getColumnIndexOrThrow(_cursor, "bundleActionEvalId");
          final int _cursorIndexOfExerciseId = CursorUtil.getColumnIndexOrThrow(_cursor, "exerciseId");
          final int _cursorIndexOfUnitLevelKey = CursorUtil.getColumnIndexOrThrow(_cursor, "unitLevelKey");
          final int _cursorIndexOfMimeType = CursorUtil.getColumnIndexOrThrow(_cursor, "mimeType");
          final int _cursorIndexOfCreatedAt = CursorUtil.getColumnIndexOrThrow(_cursor, "createdAt");
          final int _cursorIndexOfStatus = CursorUtil.getColumnIndexOrThrow(_cursor, "status");
          final List<OfflineOperationEntity> _result = new ArrayList<OfflineOperationEntity>(_cursor.getCount());
          while (_cursor.moveToNext()) {
            final OfflineOperationEntity _item;
            final String _tmpClientOperationId;
            _tmpClientOperationId = _cursor.getString(_cursorIndexOfClientOperationId);
            final String _tmpType;
            _tmpType = _cursor.getString(_cursorIndexOfType);
            final String _tmpUrl;
            _tmpUrl = _cursor.getString(_cursorIndexOfUrl);
            final String _tmpPayloadJson;
            if (_cursor.isNull(_cursorIndexOfPayloadJson)) {
              _tmpPayloadJson = null;
            } else {
              _tmpPayloadJson = _cursor.getString(_cursorIndexOfPayloadJson);
            }
            final String _tmpFileBase64;
            if (_cursor.isNull(_cursorIndexOfFileBase64)) {
              _tmpFileBase64 = null;
            } else {
              _tmpFileBase64 = _cursor.getString(_cursorIndexOfFileBase64);
            }
            final String _tmpEvaluationListItemId;
            if (_cursor.isNull(_cursorIndexOfEvaluationListItemId)) {
              _tmpEvaluationListItemId = null;
            } else {
              _tmpEvaluationListItemId = _cursor.getString(_cursorIndexOfEvaluationListItemId);
            }
            final String _tmpItemId;
            if (_cursor.isNull(_cursorIndexOfItemId)) {
              _tmpItemId = null;
            } else {
              _tmpItemId = _cursor.getString(_cursorIndexOfItemId);
            }
            final String _tmpRowIndex;
            if (_cursor.isNull(_cursorIndexOfRowIndex)) {
              _tmpRowIndex = null;
            } else {
              _tmpRowIndex = _cursor.getString(_cursorIndexOfRowIndex);
            }
            final String _tmpMediaKind;
            if (_cursor.isNull(_cursorIndexOfMediaKind)) {
              _tmpMediaKind = null;
            } else {
              _tmpMediaKind = _cursor.getString(_cursorIndexOfMediaKind);
            }
            final String _tmpBundleActionEvalId;
            if (_cursor.isNull(_cursorIndexOfBundleActionEvalId)) {
              _tmpBundleActionEvalId = null;
            } else {
              _tmpBundleActionEvalId = _cursor.getString(_cursorIndexOfBundleActionEvalId);
            }
            final String _tmpExerciseId;
            if (_cursor.isNull(_cursorIndexOfExerciseId)) {
              _tmpExerciseId = null;
            } else {
              _tmpExerciseId = _cursor.getString(_cursorIndexOfExerciseId);
            }
            final String _tmpUnitLevelKey;
            if (_cursor.isNull(_cursorIndexOfUnitLevelKey)) {
              _tmpUnitLevelKey = null;
            } else {
              _tmpUnitLevelKey = _cursor.getString(_cursorIndexOfUnitLevelKey);
            }
            final String _tmpMimeType;
            if (_cursor.isNull(_cursorIndexOfMimeType)) {
              _tmpMimeType = null;
            } else {
              _tmpMimeType = _cursor.getString(_cursorIndexOfMimeType);
            }
            final long _tmpCreatedAt;
            _tmpCreatedAt = _cursor.getLong(_cursorIndexOfCreatedAt);
            final String _tmpStatus;
            _tmpStatus = _cursor.getString(_cursorIndexOfStatus);
            _item = new OfflineOperationEntity(_tmpClientOperationId,_tmpType,_tmpUrl,_tmpPayloadJson,_tmpFileBase64,_tmpEvaluationListItemId,_tmpItemId,_tmpRowIndex,_tmpMediaKind,_tmpBundleActionEvalId,_tmpExerciseId,_tmpUnitLevelKey,_tmpMimeType,_tmpCreatedAt,_tmpStatus);
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

  @Override
  public Object countPending(final Continuation<? super Integer> $completion) {
    final String _sql = "SELECT COUNT(*) FROM offline_operations WHERE status IN ('pending', 'failed')";
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

  @NonNull
  public static List<Class<?>> getRequiredConverters() {
    return Collections.emptyList();
  }
}
