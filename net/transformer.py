import torch
from torch import nn

from einops import rearrange, repeat
from einops.layers.torch import Rearrange

def pair(t):
    return t if isinstance(t, tuple) else (t, t)



class PreNorm(nn.Module):
    def __init__(self, dim, fn):
        super().__init__()
        self.norm = nn.LayerNorm(dim)
        self.fn = fn
    def forward(self, x, **kwargs):
        return self.fn(self.norm(x), **kwargs)

class FeedForward(nn.Module):
    def __init__(self, dim, hidden_dim, dropout = 0.):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, dim),
            nn.Dropout(dropout)
        )
    def forward(self, x):
        return self.net(x)
class Attention(nn.Module):
    def __init__(self, dim, heads = 8, dim_head = 64, dropout = 0.):
        super().__init__()
        inner_dim = dim_head *  heads
        project_out = not (heads == 1 and dim_head == dim)

        self.heads = heads
        self.scale = dim_head ** -0.5

        self.attend = nn.Softmax(dim = -1)
        self.to_qkv = nn.Linear(dim, inner_dim * 3, bias = False)

        self.to_out = nn.Sequential(
            nn.Linear(inner_dim, dim),
            nn.Dropout(dropout)
        ) if project_out else nn.Identity()

    def forward(self, x):
        qkv = self.to_qkv(x).chunk(3, dim = -1)
        q, k, v = map(lambda t: rearrange(t, 'b n (h d) -> b h n d', h = self.heads), qkv)
        
        dots = torch.matmul(q, k.transpose(-1, -2)) * self.scale

        attn = self.attend(dots)
        
        out = torch.matmul(attn, v)
        out = rearrange(out, 'b h n d -> b n (h d)')
        return self.to_out(out), attn

class Transformer(nn.Module):
    def __init__(self, dim, depth, heads, dim_head, mlp_dim, dropout = 0.):
        super().__init__()
        self.layers = nn.ModuleList([])
        for _ in range(depth):
            self.layers.append(nn.ModuleList([
                PreNorm(dim, Attention(dim, heads = heads, dim_head = dim_head, dropout = dropout)),
                PreNorm(dim, FeedForward(dim, mlp_dim, dropout = dropout))
            ]))
    def forward(self, x):
        atts = []
        for attn, ff in self.layers:
            x_, att = attn(x)
            atts.append(att)
            x = x_ + x
            x = ff(x) + x
        return x, atts

class PoseTransformer(nn.Module):
    def __init__(self, *, seq_len, dim, depth, heads, mlp_dim, dim_head = 64, dropout = 0., emb_dropout = 0.):
        super().__init__()
  
        # self.to_embedding = nn.Linear(15*47*47, dim)

        self.pos_embedding = nn.Parameter(torch.randn(1, seq_len+1, dim))
        self.cls_token = nn.Parameter(torch.randn(1, 1, dim))
        self.dropout = nn.Dropout(emb_dropout)

        self.transformer = Transformer(dim, depth, heads, dim_head, mlp_dim, dropout)
        # self.linear = nn.Linear(dim, 15*47*47)

    def forward(self, x): # x = (batch, seq_len, 20)
        # x = self.to_embedding(x) # x = (batch, seq_len, dim)

        cls_tokens = repeat(self.cls_token, '() n d -> b n d', b = x.size(0))
        x = torch.cat((cls_tokens, x), dim=1)
        x += self.pos_embedding # x = (batch, seq_len+1, dim)
        x = self.dropout(x) # x = (batch, seq_len+1, dim)

        x, atts = self.transformer(x) # x = (batch, seq_len+1, dim)

        x = x[:, 0] # retrieving the class token # (batch, 1, dim)
        x = x.reshape(x.size(0), -1)
        # x = self.linear(x) 
        return x, atts

class ResNetTransformer(nn.Module):
    def __init__(self, *, seq_len, dim, depth, heads, mlp_dim, dim_head = 64, dropout = 0., emb_dropout = 0.):
        super().__init__()
  
        self.to_embedding = nn.Linear(2048, dim)

        self.pos_embedding = nn.Parameter(torch.randn(1, seq_len, dim))
        #self.cls_token = nn.Parameter(torch.randn(1, 1, dim))
        self.dropout = nn.Dropout(emb_dropout)

        self.transformer = Transformer(dim, depth, heads, dim_head, mlp_dim, dropout)
        self.linear = nn.Linear(dim, 2048)

    def forward(self, x): # x = (batch, seq_len, 20)
        x = self.to_embedding(x) # x = (batch, seq_len, dim)

        #cls_tokens = repeat(self.cls_token, '() n d -> b n d', b = x.size(0))
        #x = torch.cat((cls_tokens, x), dim=1)
        x += self.pos_embedding # x = (batch, seq_len+1, dim)
        x = self.dropout(x) # x = (batch, seq_len+1, dim)

        x, atts = self.transformer(x) # x = (batch, seq_len, dim)

        # x = x[:, 0] # retrieving the class token # (batch, 1, dim)
        # x = x.reshape(x.size(0), -1)
        x = self.linear(x) # x = (batch, seq_len, 15*47*47)
        return x, atts

class ResNetTransformerCls(nn.Module):
    def __init__(self, *, in_dim, spatial_dim, seq_len, dim, depth, heads, mlp_dim, dim_head = 64, dropout = 0., emb_dropout = 0.):
        super().__init__()
        self.spatial_dim = spatial_dim
        self.to_embedding = nn.Linear(in_dim, dim)

        self.pos_embedding = nn.Parameter(torch.randn(1, seq_len+spatial_dim, dim))
        self.cls_token = nn.Parameter(torch.randn(1, spatial_dim, dim))
        self.dropout = nn.Dropout(emb_dropout)

        self.transformer = Transformer(dim, depth, heads, dim_head, mlp_dim, dropout)
        self.linear = nn.Linear(dim, in_dim)

    def forward(self, x): # x = (batch, seq_len, 20)
        x = self.to_embedding(x) # x = (batch, seq_len, dim)
        
        cls_tokens = repeat(self.cls_token, '() n d -> b n d', b = x.size(0))
        x = torch.cat((cls_tokens, x), dim=1)
        x += self.pos_embedding # x = (batch, seq_len+144, dim)
        x = self.dropout(x) # x = (batch, seq_len+144, dim)

        x, atts = self.transformer(x) # x = (batch, seq_len+144, dim)

        x = x[:, :self.spatial_dim] # retrieving the class token # (batch, 144, dim)
        # x = x.reshape(x.size(0), -1)
        x = self.linear(x) # x = (batch, 144, 2048)
        return x, atts

class ResNetTransformerClsExp(nn.Module):
    def __init__(self, *, seq_len, dim, depth, heads, mlp_dim, dim_head = 64, dropout = 0., emb_dropout = 0.):
        super().__init__()
  
        self.to_embedding = nn.Linear(47*47, dim)

        self.pos_embedding = nn.Parameter(torch.randn(1, seq_len+(17), dim))
        self.cls_token = nn.Parameter(torch.randn(1, 17, dim))
        self.dropout = nn.Dropout(emb_dropout)

        self.transformer = Transformer(dim, depth, heads, dim_head, mlp_dim, dropout)
        self.linear = nn.Linear(dim, 47*47)

    def forward(self, x): # x = (batch, seq_len, 20)
        x = self.to_embedding(x) # x = (batch, seq_len, dim)

        cls_tokens = repeat(self.cls_token, '() n d -> b n d', b = x.size(0))
        x = torch.cat((cls_tokens, x), dim=1)
        x += self.pos_embedding # x = (batch, seq_len+144, dim)
        x = self.dropout(x) # x = (batch, seq_len+144, dim)

        x, atts = self.transformer(x) # x = (batch, seq_len+144, dim)

        x = x[:, :17] # retrieving the class token # (batch, 144, dim)
        # x = x.reshape(x.size(0), -1)
        x = self.linear(x) # x = (batch, 144, 2048)
        return x, atts

class ResNetTransformerAvg(nn.Module):
    def __init__(self, *, seq_len, dim, depth, heads, mlp_dim, dim_head = 64, dropout = 0., emb_dropout = 0.):
        super().__init__()
  
        self.to_embedding = nn.Linear(2048, dim)

        self.pos_embedding = nn.Parameter(torch.randn(1, seq_len, dim))
        self.dropout = nn.Dropout(emb_dropout)

        self.transformer = Transformer(dim, depth, heads, dim_head, mlp_dim, dropout)
        self.linear = nn.Linear(dim, 2048)

    def forward(self, x): # x = (batch, seq_len, 2048)
        x = self.to_embedding(x) # x = (batch, seq_len, dim)

        x += self.pos_embedding # x = (batch, seq_len, dim)
        x = self.dropout(x) # x = (batch, seq_len, dim)

        x, atts = self.transformer(x) # x = (batch, seq_len, dim)

        x = x.reshape(x.size(0), 144, -1, x.size(2))
        x = torch.mean(x, dim=2) # x = (batch, 144, dim)

        x = self.linear(x) # x = (batch, 144, 2048)
        return x, atts

class ResNetTransformerSlice(nn.Module):
    def __init__(self, *, seq_len, dim, depth, heads, mlp_dim, dim_head = 64, dropout = 0., emb_dropout = 0.):
        super().__init__()
  
        self.to_embedding = nn.Linear(2048, dim)

        self.pos_embedding = nn.Parameter(torch.randn(1, seq_len, dim))
        self.dropout = nn.Dropout(emb_dropout)

        self.transformer = Transformer(dim, depth, heads, dim_head, mlp_dim, dropout)
        self.linear = nn.Linear(dim, 2048)

    def forward(self, x): # x = (batch, seq_len, 2048)
        x = self.to_embedding(x) # x = (batch, seq_len, dim)

        x += self.pos_embedding # x = (batch, seq_len, dim)
        x = self.dropout(x) # x = (batch, seq_len, dim)

        x, atts = self.transformer(x) # x = (batch, seq_len, dim)

        x = x[:, -144:, :] # x = (batch, 144, dim) take last 144 tokens 

        x = self.linear(x) # x = (batch, 144, 2048)
        return x, atts

class ResNetTransformerClsRevPos(nn.Module):
    def __init__(self, *, seq_len, dim, depth, heads, mlp_dim, dim_head = 64, dropout = 0., emb_dropout = 0.):
        super().__init__()
  
        self.to_embedding = nn.Linear(2048, dim)

        self.pos_embedding = nn.Parameter(torch.randn(1, (seq_len//(12*12))+1, dim))
        self.cls_token = nn.Parameter(torch.randn(1, 12*12, dim))
        self.dropout = nn.Dropout(emb_dropout)

        self.transformer = Transformer(dim, depth, heads, dim_head, mlp_dim, dropout)
        self.linear = nn.Linear(dim, 2048)

    def forward(self, x): # x = (batch, seq_len, 2048)
        x = self.to_embedding(x) # x = (batch, seq_len, dim)

        cls_tokens = repeat(self.cls_token, '() n d -> b n d', b = x.size(0))
        x = torch.cat((cls_tokens, x), dim=1)
        x += torch.repeat_interleave(self.pos_embedding, 12*12, dim=1) # x = (batch, seq_len+144, dim)
        x = self.dropout(x) # x = (batch, seq_len+144, dim)

        x, atts = self.transformer(x) # x = (batch, seq_len+144, dim)

        x = x[:, :144] # retrieving the class token # (batch, 144, dim)
        # x = x.reshape(x.size(0), -1)
        x = self.linear(x) # x = (batch, 144, 2048)
        return x, atts

class GlobalPixelTransformer(nn.Module):
    def __init__(self, *, dim, depth, heads, mlp_dim, dim_head = 64, dropout = 0., emb_dropout = 0.):
        super().__init__()
  
        self.to_embedding = nn.Linear(2048, dim)

        self.pos_embedding = nn.Parameter(torch.randn(1, 2*(12*12), dim))
        self.cls_token = nn.Parameter(torch.randn(1, 12*12, dim))

        self.dropout = nn.Dropout(emb_dropout)

        self.transformer = Transformer(dim, depth, heads, dim_head, mlp_dim, dropout)
        self.linear = nn.Linear(dim, 2048)

    def forward(self, x): # x = (batch, seq_len, 20)
        x = self.to_embedding(x) # x = (batch, seq_len, dim)
        cls_tokens = repeat(self.cls_token, '() n d -> b n d', b = x.size(0))
        x = torch.cat((cls_tokens, x), dim=1)
        x += self.pos_embedding # x = (batch, seq_len+144, dim)
        x = self.dropout(x) # x = (batch, seq_len, dim)

        x, atts = self.transformer(x) # x = (batch, seq_len, dim)

        x = x[:, :144] # retrieving the class token # (batch, 144, dim)
        x = self.linear(x) # x = (batch, seq_len, 2048)
        return x, atts